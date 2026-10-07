import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Auditavel, Base
from app.modelos.usuario import Usuario
from app.servicos.complemento import MODELO_PADRAO
from app.servicos.documentos import formatar_documento


class Regime(enum.StrEnum):
    SIMPLES = "SIMPLES"
    PRESUMIDO = "PRESUMIDO"
    REAL = "REAL"
    MEI = "MEI"
    TERCEIRO_SETOR = "TERCEIRO_SETOR"
    OUTRO = "OUTRO"

    @property
    def rotulo(self) -> str:
        return {
            "SIMPLES": "Simples Nacional",
            "PRESUMIDO": "Lucro Presumido",
            "REAL": "Lucro Real",
            "MEI": "MEI",
            "TERCEIRO_SETOR": "Terceiro setor",
            "OUTRO": "Outro",
        }[self.value]


class Empresa(Auditavel, Base):
    """Empresa-cliente do escritório. Só o código no Domínio é obrigatório: o resto o sistema descobre."""

    __tablename__ = "empresa"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_dominio: Mapped[int] = mapped_column(unique=True)  # campo 8 do lanctos.txt
    razao_social: Mapped[str | None] = mapped_column(String(200))
    nome_curto: Mapped[str | None] = mapped_column(String(80))
    cnpj_cpf: Mapped[str | None] = mapped_column(String(14), unique=True)  # só letras e números
    regime: Mapped[Regime | None] = mapped_column(
        Enum(Regime, native_enum=False, length=20, create_constraint=True, name="regime")
    )
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    observacoes: Mapped[str | None] = mapped_column(Text)
    modelo_complemento: Mapped[str] = mapped_column(String(200), default=MODELO_PADRAO)
    ativa: Mapped[bool] = mapped_column(default=True)
    # conta individual por fornecedor (descoberta pelo plano): grupo onde ficam as contas dos fornecedores
    usa_conta_individual: Mapped[bool | None] = mapped_column()
    grupo_fornecedores: Mapped[str | None] = mapped_column(String(40))  # ex.: 2.1.3.01
    # perfil curto escrito pela IA a partir do histórico; vai junto nas classificações (§6.1.6)
    perfil_ia: Mapped[str | None] = mapped_column(Text)
    perfil_ia_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ia_ligada: Mapped[bool] = mapped_column(default=True, server_default=true())
    ia_limite_mensal_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # vazio = só o limite geral
    # campos preenchidos pelo sistema (selo "🤖 automático"); sai da lista quando o usuário altera
    campos_automaticos: Mapped[list[str]] = mapped_column(JSONB, default=list)
    dados_publicos: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # resumo da consulta do CNPJ
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    responsavel: Mapped[Usuario | None] = relationship()

    campos_nao_auditados = ("campos_automaticos", "dados_publicos", "perfil_ia_em")

    @property
    def nome(self) -> str:
        return self.nome_curto or self.razao_social or f"Empresa {self.codigo_dominio}"

    @property
    def documento_formatado(self) -> str:
        return formatar_documento(self.cnpj_cpf) if self.cnpj_cpf else ""

    def e_automatico(self, campo: str) -> bool:
        return campo in (self.campos_automaticos or [])
