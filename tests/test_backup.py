import shutil
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, make_url, select, text

from app.config import Config
from app.modelos import Log, Papel
from app.servicos import backup
from app.servicos.backup import Backup, Destinos, SituacaoBackup
from scripts.restaurar import escolher
from tests.conftest import PASTA_ARQUIVOS_TESTE, PASTA_BACKUP_TESTE, URL_TESTE, entrar

BANCO_RESTAURADO = "zera_contabil_max_teste_restaurado"


def config_teste(**valores) -> Config:
    # ignora o .env e as pastas temporárias do conftest; valores passados aqui têm prioridade
    return Config(_env_file=None, **{"pasta_backup": Path("dados/backups"), "pasta_backup_nuvem": "", **valores})


def criar_backup_falso(pasta: Path, quando: datetime, motivo: str = "automatico") -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"zera_{quando:%Y-%m-%d_%H-%M-%S}_{motivo}.dump"
    caminho.write_bytes(b"x" * 10)
    return caminho


@pytest.fixture
def pastas_limpas():
    for pasta in (PASTA_BACKUP_TESTE, PASTA_ARQUIVOS_TESTE):
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
    return PASTA_BACKUP_TESTE


@pytest.fixture
def docker(banco):
    try:
        ok = subprocess.run(["docker", "exec", backup.CONTEINER_BANCO, "true"], capture_output=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ok = None
    if ok is None or ok.returncode != 0:
        pytest.skip("o banco de teste não está no Docker deste computador")


# ---------------------------------------------------------------- onde gravar


def test_google_drive_encontrado_sozinho(tmp_path):
    drive = tmp_path / "G" / "Meu Drive"
    drive.mkdir(parents=True)
    alvos = backup.destinos(config_teste(), candidatas=[tmp_path / "nao-existe", drive])
    assert alvos.nuvem == drive / "Backups ZERA CONTABIL MAX"
    assert alvos.local.name == "backups"


def test_sem_google_drive_explica_que_o_backup_esta_so_no_computador(tmp_path):
    alvos = backup.destinos(config_teste(), candidatas=[tmp_path / "nao-existe"])
    assert alvos.nuvem is None
    assert "não está instalado" in alvos.sem_nuvem


def test_google_drive_desligado_ou_pasta_do_env(tmp_path):
    assert backup.destinos(config_teste(pasta_backup_nuvem="NAO")).nuvem is None
    escolhida = tmp_path / "Backups"
    assert backup.destinos(config_teste(pasta_backup_nuvem=str(escolhida))).nuvem == escolhida
    sumida = backup.destinos(config_teste(pasta_backup_nuvem=str(tmp_path / "X" / "Y" / "Backups")))
    assert sumida.nuvem is None and "PASTA_BACKUP_NUVEM" in sumida.sem_nuvem


# ---------------------------------------------------------------- listas e limpeza


def test_lista_so_os_backups_do_mais_recente_para_o_mais_antigo(tmp_path):
    inicio = datetime(2026, 10, 1, 8)
    for dia in range(3):
        criar_backup_falso(tmp_path, inicio + timedelta(days=dia))
    (tmp_path / "anotacao.txt").write_text("não é backup")
    (tmp_path / "zera_2026-10-09_08-00-00_automatico.dump.parcial").write_bytes(b"pela metade")
    lista = backup.listar_backups(tmp_path)
    assert [b.quando.day for b in lista] == [3, 2, 1]
    assert lista[0].rotulo_motivo == "Automático"


def test_guarda_so_os_30_mais_recentes(tmp_path):
    inicio = datetime(2026, 9, 1, 8)
    for dia in range(32):
        criar_backup_falso(tmp_path, inicio + timedelta(days=dia))
    apagados = backup.apagar_antigos(tmp_path)
    assert len(apagados) == 2
    lista = backup.listar_backups(tmp_path)
    assert len(lista) == 30
    assert lista[-1].quando == inicio + timedelta(days=2)


def test_espelho_dos_arquivos_copia_so_os_novos_e_nunca_apaga(tmp_path):
    origem, destino = tmp_path / "arquivos", tmp_path / "backup" / "arquivos"
    (origem / "ab").mkdir(parents=True)
    (origem / "ab" / "abc.pdf").write_bytes(b"extrato")
    (origem / "ab" / "abd.txt.parcial").write_bytes(b"sendo gravado")
    assert backup.espelhar_arquivos(origem, destino) == 1
    assert (destino / "ab" / "abc.pdf").read_bytes() == b"extrato"
    assert not (destino / "ab" / "abd.txt.parcial").exists()
    assert backup.espelhar_arquivos(origem, destino) == 0  # já estava lá
    shutil.rmtree(origem)
    assert backup.espelhar_arquivos(origem, destino) == 0
    assert (destino / "ab" / "abc.pdf").exists()  # pasta de origem vazia não apaga o backup


def test_situacao_atrasada_e_backup_do_dia(tmp_path):
    agora = datetime(2026, 10, 7, 9)
    local, nuvem = tmp_path / "local", tmp_path / "nuvem"
    alvos = Destinos(local, nuvem)
    vazia = SituacaoBackup(alvos, [], [], momento=agora)
    assert vazia.atrasado and vazia.precisa_backup()

    ontem = Backup(local / "a.dump", agora - timedelta(hours=10), "automatico", 1)
    so_local = SituacaoBackup(alvos, [ontem], [], momento=agora)
    assert not so_local.atrasado
    assert so_local.precisa_backup()  # o Google Drive ainda não tem cópia
    assert not SituacaoBackup(Destinos(local, None), [ontem], [], momento=agora).precisa_backup()

    velho = Backup(local / "b.dump", agora - timedelta(days=3), "manual", 1)
    atrasada = SituacaoBackup(Destinos(local, None), [velho], [], momento=agora)
    assert atrasada.atrasado and atrasada.dias_sem_backup == 3


def test_lista_junta_computador_e_google_drive(tmp_path):
    quando = datetime(2026, 10, 7, 9)
    no_pc = Backup(tmp_path / "zera_x.dump", quando, "automatico", 1)
    na_nuvem = Backup(tmp_path / "nuvem" / "zera_x.dump", quando, "automatico", 1)
    situacao = SituacaoBackup(Destinos(tmp_path, tmp_path / "nuvem"), [no_pc], [na_nuvem])
    assert [(linha["computador"], linha["nuvem"]) for linha in situacao.lista()] == [(True, True)]


def test_escolher_backup_na_restauracao():
    opcoes = [(Backup(Path(f"{n}.dump"), datetime(2026, 10, n), "automatico", 1), "computador") for n in (3, 2, 1)]
    assert escolher(opcoes, "").caminho.name == "3.dump"
    assert escolher(opcoes, " 2 ").caminho.name == "2.dump"
    assert escolher(opcoes, "9") is None
    assert escolher(opcoes, "abc") is None


def test_backup_automatico_avisa_registra_e_continua(monkeypatch, capsys):
    falhas = []

    def falhar():
        raise backup.ErroBackup("o banco de dados está desligado")

    monkeypatch.setattr(backup, "situacao", falhar)
    monkeypatch.setattr(backup, "registrar_falha", lambda erro, usuario_id=None: falhas.append(str(erro)))
    from scripts.iniciar import backup_automatico

    parar = threading.Event()
    parar.set()  # uma volta só
    backup_automatico(parar, checar_a_cada_segundos=0)
    assert "backup automático não foi feito" in capsys.readouterr().out
    assert falhas == ["o banco de dados está desligado"]


def test_dois_backups_ao_mesmo_tempo_nao():
    assert backup._trava.acquire(blocking=False)
    try:
        with pytest.raises(backup.ErroBackup, match="Já tem um backup"):
            backup.fazer_backup("manual")
    finally:
        backup._trava.release()


# ---------------------------------------------------------------- de verdade (PostgreSQL no Docker)


@pytest.mark.banco
def test_backup_de_verdade_volta_os_dados(docker, pastas_limpas, criar_usuario, sessao, monkeypatch, tmp_path):
    criar_usuario("ana")
    (PASTA_ARQUIVOS_TESTE / "ab").mkdir()
    (PASTA_ARQUIVOS_TESTE / "ab" / "abc.pdf").write_bytes(b"extrato de teste")
    nuvem = tmp_path / "Meu Drive" / "Backups ZERA CONTABIL MAX"
    monkeypatch.setattr(backup, "destinos", lambda config=None: Destinos(PASTA_BACKUP_TESTE, nuvem))

    resultado = backup.fazer_backup("manual")

    assert resultado.tabelas >= 10
    assert resultado.backup.caminho.parent == PASTA_BACKUP_TESTE
    assert resultado.na_nuvem == nuvem / resultado.backup.nome
    assert (nuvem / "arquivos" / "ab" / "abc.pdf").exists()
    assert not list(PASTA_BACKUP_TESTE.glob("*.parcial"))
    log = sessao.scalar(select(Log).where(Log.acao == "BACKUP"))
    assert resultado.backup.nome in log.detalhe and "Google Drive" in log.detalhe

    # some um arquivo original e o backup é restaurado num banco à parte
    shutil.rmtree(PASTA_ARQUIVOS_TESTE / "ab")
    try:
        assert backup.restaurar_backup(resultado.na_nuvem, BANCO_RESTAURADO) == 1
        assert (PASTA_ARQUIVOS_TESTE / "ab" / "abc.pdf").read_bytes() == b"extrato de teste"
        motor = create_engine(make_url(URL_TESTE).set(database=BANCO_RESTAURADO))
        with motor.connect() as conexao:
            assert conexao.scalar(text("select login from usuario")) == "ana"
        motor.dispose()
    finally:
        backup._psql(make_url(URL_TESTE).username, f'DROP DATABASE IF EXISTS "{BANCO_RESTAURADO}" WITH (FORCE)')


@pytest.mark.banco
def test_backup_estragado_nao_apaga_nada(docker, tmp_path):
    estragado = tmp_path / "zera_2026-10-07_09-00-00_manual.dump"
    estragado.write_bytes(b"isto nao e um backup")
    with pytest.raises(backup.ErroBackup, match="Nada foi alterado"):
        backup.restaurar_backup(estragado, BANCO_RESTAURADO)
    resultado = subprocess.run(
        ["docker", "exec", backup.CONTEINER_BANCO, "psql", "-U", "zera", "-d", "postgres", "-Atc",
         f"select count(*) from pg_database where datname like '{BANCO_RESTAURADO}%'"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert resultado.stdout.strip() == "0"  # nem o banco provisório ficou para trás


# ---------------------------------------------------------------- tela


@pytest.mark.banco
def test_tela_de_backup_e_aviso_na_tela_inicial(cliente, criar_usuario, pastas_limpas):
    criar_usuario("ana")
    criar_usuario("bia", papel=Papel.ASSISTENTE)
    entrar(cliente, "ana")
    assert "Nenhum backup foi feito ainda" in cliente.get("/").text
    tela = cliente.get("/backup").text
    assert "Nenhum backup feito ainda" in tela
    assert "desligada no .env" in tela  # nos testes o Google Drive fica desligado

    criar_backup_falso(pastas_limpas, backup.agora() - timedelta(hours=1), "manual")
    tela = cliente.get("/backup").text
    assert "em dia" in tela and "Feito na tela" in tela
    assert "Nenhum backup foi feito" not in cliente.get("/").text
    assert "só neste computador" in cliente.get("/").text

    cliente.post("/sair")
    entrar(cliente, "bia")
    assert cliente.get("/backup").status_code == 403
    assert "backup" not in cliente.get("/").text.lower()


@pytest.mark.banco
def test_botao_fazer_backup_agora(docker, cliente, criar_usuario, pastas_limpas, sessao):
    ana = criar_usuario("ana")
    entrar(cliente, "ana")
    tela = cliente.post("/backup", follow_redirects=True).text
    assert "gravado só neste computador" in tela
    assert len(backup.listar_backups(pastas_limpas)) == 1
    assert sessao.scalar(select(func.count()).select_from(Log).where(Log.acao == "BACKUP", Log.usuario_id == ana.id))
