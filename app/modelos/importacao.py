from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Base
from app.modelos.usuario import Usuario


class ArquivoOriginal(Base):
    """Arquivo enviado (plano, Diário/Razão, extrato), guardado por 5 anos (§7.3)."""

    __tablename__ = "arquivo_original"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # PLANO, DIARIO, RAZAO, EXTRATO
    nome_original: Mapped[str] = mapped_column(String(255))
    # onde o arquivo está no armazenamento (app/servicos/armazenamento.py)
    chave: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    tamanho: Mapped[int]
    enviado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    expira_em: Mapped[date]


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
