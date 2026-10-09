from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Base
from app.modelos.empresa import Empresa


class ChamadaIA(Base):
    """Cada chamada à API da Anthropic, com tokens e custo estimado (§6.4) — inclusive as que falharam."""

    __tablename__ = "chamada_ia"

    id: Mapped[int] = mapped_column(primary_key=True)
    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresa.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    finalidade: Mapped[str] = mapped_column(String(40))  # ex.: auto_configuracao, classificacao, teste
    modelo: Mapped[str] = mapped_column(String(60))
    sucesso: Mapped[bool]
    erro: Mapped[str | None] = mapped_column(Text)
    tokens_entrada: Mapped[int] = mapped_column(default=0)
    tokens_saida: Mapped[int] = mapped_column(default=0)
    tokens_cache_escrita: Mapped[int] = mapped_column(default=0)
    tokens_cache_leitura: Mapped[int] = mapped_column(default=0)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    duracao_ms: Mapped[int] = mapped_column(default=0)
    request_id: Mapped[str | None] = mapped_column(String(80))
    entrada_resumo: Mapped[str | None] = mapped_column(Text)  # começo da pergunta, para auditoria
    resposta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    empresa: Mapped[Empresa | None] = relationship()
