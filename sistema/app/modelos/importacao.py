from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Base
from app.modelos.usuario import Usuario


class ArquivoOriginal(Base):
    """Arquivo enviado (plano, Diário/Razão, extrato), guardado por 5 anos (§7.3)."""

    __tablename__ = "arquivo_original"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # PLANO, DIARIO, RAZAO, EXTRATO, EXPORTACAO
    nome_original: Mapped[str] = mapped_column(String(255))
    # onde o arquivo está no armazenamento (app/servicos/armazenamento.py)
    chave: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    tamanho: Mapped[int]
    enviado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    expira_em: Mapped[date]
    # passou dos 5 anos: o arquivo foi apagado (§7.3); o registro fica (quem enviou, quando, nome, SHA-256)
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Importacao(Base):
    """Cada importação feita (plano, Diário, extrato...) com o resumo e os avisos."""

    __tablename__ = "importacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    arquivo_id: Mapped[int | None] = mapped_column(ForeignKey("arquivo_original.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resumo: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    avisos: Mapped[list[str]] = mapped_column(JSONB, default=list)

    arquivo: Mapped[ArquivoOriginal | None] = relationship()
    usuario: Mapped[Usuario | None] = relationship()


class ArquivoPasta(Base):
    """Cada arquivo que a busca na pasta do cliente já olhou (pasta de entrada): a próxima busca pula o que não mudou
    (mesmo caminho, tamanho e data) e não repete o mesmo aviso. O arquivo em si continua só na pasta do cliente."""

    __tablename__ = "arquivo_pasta"
    __table_args__ = (UniqueConstraint("empresa_id", "caminho"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    caminho: Mapped[str] = mapped_column(String(500))
    tamanho: Mapped[int]
    modificado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    # LIDO (virou extrato), IGUAL (nada novo: cópia ou PDF do que o OFX trouxe), SEM_LEITOR (PDF que só a IA lê),
    # PLANILHA (não é lida sozinha: pode não ser extrato) ou ERRO (tenta de novo na próxima busca)
    resultado: Mapped[str] = mapped_column(String(12))
    detalhe: Mapped[str | None] = mapped_column(Text)
    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
