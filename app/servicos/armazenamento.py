"""Guarda os arquivos originais enviados (planos, Diários, extratos) por 5 anos (§7.3).

Hoje numa pasta do computador (PASTA_ARQUIVOS do .env). Na nuvem (Fase 4) basta criar um
ArmazenamentoSupabase com os mesmos três métodos e devolvê-lo em `obter_armazenamento`.
Cada arquivo é guardado pelo seu SHA-256: o mesmo arquivo enviado duas vezes ocupa espaço uma vez só.
"""

import hashlib
from datetime import date
from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session

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
