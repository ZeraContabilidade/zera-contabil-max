from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Auditavel, Base
from app.modelos.plano import ContaContabil


class ContaChave(Auditavel, Base):
    """Conta que a empresa usa para cada finalidade: banco, rendimentos, IR retido, tarifas... (§3.2.1).

    Descoberta sozinha (REGRA ou IA) a partir do plano; o usuário pode trocar (USUARIO), e a
    escolha do usuário nunca é sobrescrita pela auto-configuração.
    """

    __tablename__ = "conta_chave"
    __table_args__ = (UniqueConstraint("empresa_id", "tipo", "referencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))  # ver app/servicos/contas_chave.py
    # só nas contas bancárias: banco + número, ex.: "BB conta 72637-0"
    referencia: Mapped[str] = mapped_column(String(80), default="")
    conta_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))  # vazio = não encontrada
    origem: Mapped[str] = mapped_column(String(10))  # REGRA, IA ou USUARIO
    confianca: Mapped[int] = mapped_column(default=0)  # 0 a 100
    justificativa: Mapped[str | None] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conta: Mapped[ContaContabil | None] = relationship()

    campos_nao_auditados = ("atualizado_em",)
