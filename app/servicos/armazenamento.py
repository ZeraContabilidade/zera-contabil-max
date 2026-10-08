"""Guarda os arquivos originais enviados (planos, Diários, extratos) e os lanctos.txt gerados por 5 anos (§7.3).

Hoje numa pasta do computador (PASTA_ARQUIVOS do .env). Na nuvem (Fase 4) basta criar um
ArmazenamentoSupabase com os mesmos três métodos e devolvê-lo em `obter_armazenamento`.
Cada arquivo é guardado pelo seu SHA-256: o mesmo arquivo enviado duas vezes ocupa espaço uma vez só.
Depois de 5 anos `apagar_vencidos` (rodado todo dia pelo INICIAR.bat) apaga o arquivo e deixa o registro.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.config import obter_config
from app.modelos import ArquivoOriginal, Empresa, Usuario
from app.servicos.competencia import hoje

ANOS_DE_GUARDA = 5


class Armazenamento(Protocol):
    def salvar(self, conteudo: bytes, nome: str) -> str: ...
    def ler(self, chave: str) -> bytes: ...
    def apagar(self, chave: str) -> None: ...


class ArmazenamentoLocal:
    def __init__(self, pasta: Path):
        self.pasta = pasta

    def _caminho(self, chave: str) -> Path:
        caminho = (self.pasta / chave).resolve()
        if not caminho.is_relative_to(self.pasta.resolve()):
            raise ValueError(f"Chave de arquivo inválida: {chave}")
        return caminho

    def salvar(self, conteudo: bytes, nome: str) -> str:
        sha = hashlib.sha256(conteudo).hexdigest()
        extensao = "".join(c for c in Path(nome).suffix.lower() if c.isalnum() or c == ".")[:10]
        chave = f"{sha[:2]}/{sha}{extensao}"
        caminho = self._caminho(chave)
        if not caminho.exists():
            caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = caminho.with_suffix(caminho.suffix + ".parcial")
            temporario.write_bytes(conteudo)
            temporario.replace(caminho)  # nunca fica arquivo pela metade
        return chave

    def ler(self, chave: str) -> bytes:
        return self._caminho(chave).read_bytes()

    def apagar(self, chave: str) -> None:
        self._caminho(chave).unlink(missing_ok=True)


def obter_armazenamento() -> Armazenamento:
    config = obter_config()
    return ArmazenamentoLocal(config.caminho(config.pasta_arquivos))


def _daqui_a_anos(dia: date, anos: int) -> date:
    try:
        return dia.replace(year=dia.year + anos)
    except ValueError:  # 29 de fevereiro
        return dia.replace(year=dia.year + anos, day=28)


def guardar_arquivo(
    sessao: Session, empresa: Empresa, tipo: str, nome: str, conteudo: bytes, usuario: Usuario | None
) -> ArquivoOriginal:
    chave = obter_armazenamento().salvar(conteudo, nome)
    arquivo = ArquivoOriginal(
        empresa_id=empresa.id,
        tipo=tipo,
        nome_original=Path(nome).name[:255] or "arquivo",
        chave=chave,
        sha256=hashlib.sha256(conteudo).hexdigest(),
        tamanho=len(conteudo),
        enviado_por_id=usuario.id if usuario else None,
        expira_em=_daqui_a_anos(hoje(), ANOS_DE_GUARDA),
    )
    sessao.add(arquivo)
    sessao.flush()
    return arquivo


class ArquivoApagado(Exception):
    """O arquivo passou dos 5 anos de guarda e foi apagado (o registro continua)."""


def ler_arquivo(arquivo: ArquivoOriginal) -> bytes:
    if arquivo.excluido_em is not None:
        raise ArquivoApagado(
            f"O arquivo “{arquivo.nome_original}” foi apagado em {arquivo.excluido_em:%d/%m/%Y} "
            "(guarda de 5 anos). Se precisar dele, procure nos backups antigos."
        )
    return obter_armazenamento().ler(arquivo.chave)


@dataclass
class ResultadoGuarda:
    apagados: list[ArquivoOriginal] = field(default_factory=list)
    bytes_liberados: int = 0

    def resumo(self) -> str:
        nomes = ", ".join(a.nome_original for a in self.apagados[:10])
        mais = f" e mais {len(self.apagados) - 10}" if len(self.apagados) > 10 else ""
        megas = self.bytes_liberados / 1_000_000
        return f"{len(self.apagados)} arquivo(s) com mais de 5 anos apagado(s) ({megas:.1f} MB): {nomes}{mais}."


def apagar_vencidos(sessao: Session, dia: date | None = None) -> ResultadoGuarda:
    """Apaga os arquivos cuja guarda de 5 anos venceu (o registro fica, com a data). O mesmo conteúdo enviado de
    novo depois (mesma chave) só sai do disco quando todos os registros dele tiverem vencido."""
    dia = dia or hoje()
    resultado = ResultadoGuarda()
    vencidos = list(
        sessao.scalars(
            select(ArquivoOriginal).where(ArquivoOriginal.expira_em < dia, ArquivoOriginal.excluido_em.is_(None))
        )
    )
    if not vencidos:
        return resultado
    agora = datetime.now(UTC)
    for arquivo in vencidos:
        arquivo.excluido_em = agora
    sessao.flush()
    armazenamento = obter_armazenamento()
    for chave in sorted({a.chave for a in vencidos}):
        ainda_usada = sessao.scalar(
            select(ArquivoOriginal.id).where(ArquivoOriginal.chave == chave, ArquivoOriginal.excluido_em.is_(None))
        )
        if ainda_usada is None:
            armazenamento.apagar(chave)
            resultado.bytes_liberados += next(a.tamanho for a in vencidos if a.chave == chave)
    resultado.apagados = vencidos
    registrar_evento(sessao, "APAGAR_ARQUIVOS_VENCIDOS", detalhe=resultado.resumo())
    return resultado
