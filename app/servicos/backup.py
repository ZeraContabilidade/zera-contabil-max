"""Backup (§7.2): cópia do banco de dados (pg_dump) + arquivos originais, todo dia e ao iniciar.

Cada backup é um arquivo `zera_AAAA-MM-DD_HH-MM-SS_<motivo>.dump` gravado na pasta deste computador
(PASTA_BACKUP) e copiado para o Google Drive (PASTA_BACKUP_NUVEM; em branco = o sistema encontra sozinho).
Os arquivos originais nunca mudam (o nome é o SHA-256), então ficam espelhados em `<pasta>/arquivos`
copiando só os novos. Cada pasta guarda os 30 backups mais recentes.

A restauração monta o backup num banco à parte e só troca pelo atual se tudo deu certo:
um backup estragado nunca apaga os dados que estão em uso.
"""

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import make_url

from app.auditoria import registrar_evento
from app.config import Config, obter_config
from app.db import fabrica_sessoes

CONTEINER_BANCO = "zera-contabil-max-banco"  # docker-compose.yml
NOME_PASTA_NUVEM = "Backups ZERA CONTABIL MAX"
MANTER = 30
INTERVALO = timedelta(hours=20)  # backup automático: um por dia (na 1ª abertura do dia ou com o sistema aberto)
ATRASO_PARA_AVISO = timedelta(days=2)
MOTIVOS = {"automatico": "Automático", "manual": "Feito na tela", "antes-de-restaurar": "Antes de restaurar"}
_NOME = re.compile(r"^zera_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_([a-z-]+)\.dump$")
_NOME_BANCO = re.compile(r"^[a-z0-9_]{1,50}$")
_trava = threading.Lock()  # o automático e o botão da tela nunca rodam juntos


class ErroBackup(Exception):
    """Falha no backup ou na restauração, com mensagem dizendo o que fazer."""


def agora() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None, microsecond=0)


@dataclass(frozen=True)
class Backup:
    caminho: Path
    quando: datetime
    motivo: str
    tamanho: int

    @property
    def nome(self) -> str:
        return self.caminho.name

    @property
    def rotulo_motivo(self) -> str:
        return MOTIVOS.get(self.motivo, self.motivo)


@dataclass(frozen=True)
class Destinos:
    local: Path
    nuvem: Path | None
    sem_nuvem: str = ""  # por que não há cópia na nuvem (vazio quando há)


# ---------------------------------------------------------------- onde gravar


def candidatas_google_drive() -> list[Path]:
    """Lugares onde o Google Drive para computador costuma ficar (unidade G: ou pasta do usuário)."""
    unidades = [Path(u) for u in getattr(os, "listdrives", list)()]
    casa = Path.home()
    return [u / nome for u in unidades for nome in ("Meu Drive", "My Drive")] + [
        casa / "Meu Drive",
        casa / "My Drive",
        casa / "Google Drive",
    ]


def encontrar_google_drive(candidatas: list[Path] | None = None) -> Path | None:
    for pasta in candidatas_google_drive() if candidatas is None else candidatas:
        try:
            if pasta.is_dir():
                return pasta
        except OSError:  # unidade de rede desconectada
            continue
    return None


def destinos(config: Config | None = None, candidatas: list[Path] | None = None) -> Destinos:
    config = config or obter_config()
    local = config.caminho(config.pasta_backup)
    valor = config.pasta_backup_nuvem.strip().strip('"')
    if valor.upper() in ("NAO", "NÃO"):
        return Destinos(local, None, "A cópia no Google Drive está desligada no .env (PASTA_BACKUP_NUVEM=NAO).")
    if valor:
        pasta = Path(valor)
        if pasta.is_dir() or pasta.parent.is_dir():
            return Destinos(local, pasta)
        return Destinos(
            local,
            None,
            f"Não encontrei a pasta {pasta} (PASTA_BACKUP_NUVEM do .env). "
            "Veja se o Google Drive está aberto e conectado na sua conta.",
        )
    drive = encontrar_google_drive(candidatas)
    if drive:
        return Destinos(local, drive / NOME_PASTA_NUVEM)
    return Destinos(
        local,
        None,
        "O Google Drive para computador não está instalado neste computador (ou não está conectado). "
        "Os backups estão só aqui: se o computador estragar, eles se perdem junto.",
    )


# ---------------------------------------------------------------- listas


def _ler_nome(caminho: Path) -> Backup | None:
    if not (achado := _NOME.match(caminho.name)):
        return None
    try:
        quando = datetime.strptime(achado.group(1), "%Y-%m-%d_%H-%M-%S")
        return Backup(caminho, quando, achado.group(2), caminho.stat().st_size)
    except (ValueError, OSError):
        return None


def listar_backups(pasta: Path | None) -> list[Backup]:
    """Backups da pasta, do mais recente para o mais antigo."""
    if pasta is None or not pasta.is_dir():
        return []
    backups = [b for caminho in pasta.glob("zera_*.dump") if (b := _ler_nome(caminho))]
    return sorted(backups, key=lambda b: b.quando, reverse=True)


def apagar_antigos(pasta: Path, manter: int = MANTER) -> list[Path]:
    antigos = [b.caminho for b in listar_backups(pasta)[manter:]]
    for caminho in antigos:
        caminho.unlink(missing_ok=True)
    return antigos


@dataclass
class SituacaoBackup:
    destinos: Destinos
    local: list[Backup]
    nuvem: list[Backup]
    momento: datetime = field(default_factory=agora)

    @property
    def ultimo(self) -> Backup | None:
        todos = self.local + self.nuvem
        return max(todos, key=lambda b: b.quando) if todos else None

    @property
    def atrasado(self) -> bool:
        return self.ultimo is None or self.momento - self.ultimo.quando > ATRASO_PARA_AVISO

    @property
    def dias_sem_backup(self) -> int:
        return (self.momento - self.ultimo.quando).days if self.ultimo else 0

    def precisa_backup(self) -> bool:
        """Falta o backup do dia aqui — ou no Google Drive, que pode ter sido instalado agora."""
        pastas = [self.local] + ([self.nuvem] if self.destinos.nuvem else [])
        return any(not lista or self.momento - lista[0].quando >= INTERVALO for lista in pastas)

    def lista(self) -> list[dict]:
        """Uma linha por backup, dizendo se está no computador, no Google Drive ou nos dois."""
        linhas: dict[str, dict] = {}
        for onde, lista in (("computador", self.local), ("nuvem", self.nuvem)):
            for b in lista:
                linhas.setdefault(b.nome, {"backup": b, "computador": False, "nuvem": False})[onde] = True
        return sorted(linhas.values(), key=lambda linha: linha["backup"].quando, reverse=True)


def situacao(config: Config | None = None) -> SituacaoBackup:
    alvos = destinos(config)
    return SituacaoBackup(alvos, listar_backups(alvos.local), listar_backups(alvos.nuvem))


# ---------------------------------------------------------------- banco de dados (pelo Docker)


def _alvo_banco(nome_banco: str | None = None) -> tuple[str, str]:
    url = make_url(obter_config().url_banco())
    if url.host not in ("127.0.0.1", "localhost"):
        raise ErroBackup("O backup automático só funciona com o banco de dados no Docker deste computador.")
    banco = nome_banco or url.database or ""
    if not _NOME_BANCO.match(banco) or not _NOME_BANCO.match(url.username or ""):
        raise ErroBackup(f"Nome de banco de dados inesperado no .env: {banco}")
    return url.username, banco


def _docker(*args: str, entrada=None, saida=None, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", *args],
            stdin=entrada,
            stdout=saida if saida is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as erro:
        raise ErroBackup("Não encontrei o Docker neste computador. Abra o sistema pelo INICIAR.bat.") from erro
    except subprocess.TimeoutExpired as erro:
        raise ErroBackup("O Docker demorou demais para responder. Veja se o Docker Desktop está aberto.") from erro


def _erro_docker(resultado: subprocess.CompletedProcess) -> str:
    texto = resultado.stderr.decode("utf-8", "replace").strip()
    if "No such container" in texto or "is not running" in texto:
        return "o banco de dados está desligado. Abra o sistema pelo INICIAR.bat (ele liga o banco)"
    return texto[-500:] or "erro desconhecido"


def gerar_dump(destino: Path, nome_banco: str | None = None) -> int:
    """Grava a cópia do banco e confere se ela abre. Devolve quantas tabelas a cópia tem."""
    usuario, banco = _alvo_banco(nome_banco)
    with destino.open("wb") as saida:
        resultado = _docker("exec", CONTEINER_BANCO, "pg_dump", "-U", usuario, "-Fc", banco, saida=saida)
    if resultado.returncode != 0:
        raise ErroBackup(f"O banco de dados não gerou a cópia: {_erro_docker(resultado)}.")
    with destino.open("rb") as entrada:
        indice = _docker("exec", "-i", CONTEINER_BANCO, "pg_restore", "-l", entrada=entrada, timeout=120)
    if indice.returncode != 0:
        raise ErroBackup(f"A cópia do banco saiu estragada: {_erro_docker(indice)}.")
    linhas = indice.stdout.decode("utf-8", "replace").splitlines()
    return sum(1 for linha in linhas if " TABLE public " in linha)


def _psql(usuario: str, comando: str) -> None:
    resultado = _docker(
        "exec", CONTEINER_BANCO, "psql", "-U", usuario, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", comando
    )
    if resultado.returncode != 0:
        raise ErroBackup(f"O banco de dados recusou a restauração: {_erro_docker(resultado)}.")


def restaurar_banco(arquivo: Path, nome_banco: str | None = None) -> None:
    """Troca o banco pelo do backup. Monta tudo num banco à parte e só troca se deu certo."""
    usuario, banco = _alvo_banco(nome_banco)
    provisorio = f"{banco}_restaurando"
    _psql(usuario, f'DROP DATABASE IF EXISTS "{provisorio}" WITH (FORCE)')
    _psql(usuario, f'CREATE DATABASE "{provisorio}"')
    with arquivo.open("rb") as entrada:
        resultado = _docker(
            "exec", "-i", CONTEINER_BANCO, "pg_restore", "-U", usuario, "-d", provisorio,
            "--no-owner", "--no-privileges", "--exit-on-error",
            entrada=entrada,
        )  # fmt: skip
    if resultado.returncode != 0:
        _psql(usuario, f'DROP DATABASE IF EXISTS "{provisorio}" WITH (FORCE)')
        raise ErroBackup(
            f"O backup {arquivo.name} não pôde ser lido ({_erro_docker(resultado)}). "
            "Nada foi alterado: escolha outro backup."
        )
    _psql(usuario, f'DROP DATABASE IF EXISTS "{banco}" WITH (FORCE)')
    _psql(usuario, f'ALTER DATABASE "{provisorio}" RENAME TO "{banco}"')


# ---------------------------------------------------------------- arquivos


def _copiar(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".parcial")
    shutil.copy2(origem, temporario)
    temporario.replace(destino)  # nunca fica arquivo pela metade


def espelhar_arquivos(origem: Path, destino: Path) -> int:
    """Copia os arquivos que ainda não estão no destino. Devolve quantos copiou.
    Nunca apaga nada no destino (uma pasta de origem vazia por engano não destrói o backup)."""
    if not origem.is_dir():
        return 0
    novos = 0
    for arquivo in origem.rglob("*"):
        if not arquivo.is_file() or arquivo.suffix == ".parcial":
            continue
        alvo = destino / arquivo.relative_to(origem)
        if alvo.is_file() and alvo.stat().st_size == arquivo.stat().st_size:
            continue
        _copiar(arquivo, alvo)
        novos += 1
    return novos


# ---------------------------------------------------------------- backup e restauração


@dataclass
class ResultadoBackup:
    backup: Backup
    tabelas: int
    arquivos_novos: int
    na_nuvem: Path | None = None
    aviso_nuvem: str = ""

    def resumo(self) -> str:
        texto = f"Backup {self.backup.nome} ({self.tabelas} tabelas)"
        if self.na_nuvem:
            return texto + f" gravado neste computador e no Google Drive ({self.na_nuvem.parent})."
        return texto + f" gravado só neste computador ({self.backup.caminho.parent}). {self.aviso_nuvem}"


def fazer_backup(motivo: str = "automatico", usuario_id: int | None = None, nuvem: bool = True) -> ResultadoBackup:
    if not _trava.acquire(blocking=False):
        raise ErroBackup("Já tem um backup sendo feito agora. Espere um minuto e atualize a página.")
    try:
        return _fazer_backup(motivo, usuario_id, nuvem)
    finally:
        _trava.release()


def _fazer_backup(motivo: str, usuario_id: int | None, nuvem: bool) -> ResultadoBackup:
    config = obter_config()
    alvos = destinos(config)
    nome = f"zera_{agora():%Y-%m-%d_%H-%M-%S}_{motivo}.dump"
    try:
        alvos.local.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        raise ErroBackup(f"Não consegui criar a pasta de backup {alvos.local}: {erro}") from erro
    temporario = alvos.local / (nome + ".parcial")
    try:
        tabelas = gerar_dump(temporario)
        temporario.replace(alvos.local / nome)
    finally:
        temporario.unlink(missing_ok=True)
    pasta_arquivos = config.caminho(config.pasta_arquivos)
    novos = espelhar_arquivos(pasta_arquivos, alvos.local / "arquivos")
    apagar_antigos(alvos.local)
    resultado = ResultadoBackup(_ler_nome(alvos.local / nome), tabelas, novos)

    if not nuvem:
        resultado.aviso_nuvem = "Cópia de segurança feita só neste computador."
    elif alvos.nuvem is None:
        resultado.aviso_nuvem = alvos.sem_nuvem
    else:
        try:
            _copiar(alvos.local / nome, alvos.nuvem / nome)
            espelhar_arquivos(pasta_arquivos, alvos.nuvem / "arquivos")
            apagar_antigos(alvos.nuvem)
            resultado.na_nuvem = alvos.nuvem / nome
        except OSError as erro:
            resultado.aviso_nuvem = f"Não consegui copiar para o Google Drive ({erro}). Veja se ele está conectado."

    with fabrica_sessoes()() as sessao:
        registrar_evento(sessao, "BACKUP", usuario_id, resultado.resumo())
        sessao.commit()
    return resultado


def registrar_falha(erro: Exception, usuario_id: int | None = None) -> None:
    try:
        with fabrica_sessoes()() as sessao:
            registrar_evento(sessao, "BACKUP_FALHOU", usuario_id, str(erro))
            sessao.commit()
    except Exception:  # noqa: BLE001 — com o banco fora do ar não há onde registrar; o aviso já saiu na tela
        pass


def restaurar_backup(arquivo: Path, nome_banco: str | None = None) -> int:
    """Troca o banco pelo do backup e devolve os arquivos originais que faltam. Devolve quantos voltaram."""
    restaurar_banco(arquivo, nome_banco)
    config = obter_config()
    return espelhar_arquivos(arquivo.parent / "arquivos", config.caminho(config.pasta_arquivos))
