import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, false, func, true
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


LIMIAR_PADRAO = 90  # aprovação automática a partir de 90% de confiança
LIMIAR_MINIMO = 70  # abaixo disso a sugestão é “pendente”, nunca aprovada sozinha


class Empresa(Auditavel, Base):
    """Empresa-cliente do escritório. Só o código no Domínio é obrigatório: o resto o sistema descobre."""

    __tablename__ = "empresa"
    # cada filial é um cadastro: o código da matriz pode repetir, a filial não (sem filial também conta como valor)
    __table_args__ = (UniqueConstraint("codigo_dominio", "codigo_filial", postgresql_nulls_not_distinct=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_dominio: Mapped[int] = mapped_column()  # código da empresa (da matriz, se for filial) no Domínio
    codigo_filial: Mapped[int | None] = mapped_column()  # preenchido → vai no campo 8 do lanctos.txt no lugar do acima
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
    # sugestão com esta confiança ou mais já vem aprovada (§3.5: configurável por empresa, padrão 90)
    limiar_aprovacao: Mapped[int] = mapped_column(default=LIMIAR_PADRAO, server_default=str(LIMIAR_PADRAO))
    # mês todo aprovado + saldo conferido → o lanctos.txt sai sozinho (§6.5); desligado até o Supervisor confiar
    exportacao_automatica: Mapped[bool] = mapped_column(default=False, server_default=false())
    # pasta onde o cliente deixa os extratos (ex.: no Z:\); o sistema só lê — nunca altera nada lá
    pasta_extratos: Mapped[str | None] = mapped_column(String(400))
    # campos preenchidos pelo sistema (selo "🤖 automático"); sai da lista quando o usuário altera
    campos_automaticos: Mapped[list[str]] = mapped_column(JSONB, default=list)
    dados_publicos: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # resumo da consulta do CNPJ
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    responsavel: Mapped[Usuario | None] = relationship()

    campos_nao_auditados = ("campos_automaticos", "dados_publicos", "perfil_ia_em")

    @property
    def nome(self) -> str:
        return self.nome_curto or self.razao_social or f"Empresa {self.rotulo_codigo}"

    @property
    def codigo_no_lanctos(self) -> int:
        """Campo 8 do lanctos.txt (“Código Matriz/Filial”): o da filial, se houver; senão o da empresa."""
        return self.codigo_filial or self.codigo_dominio

    @property
    def rotulo_codigo(self) -> str:
        """Como o código aparece nas telas e mensagens: “230” ou “230 · filial 231”."""
        if self.codigo_filial:
            return f"{self.codigo_dominio} · filial {self.codigo_filial}"
        return str(self.codigo_dominio)

    @property
    def codigo_arquivo(self) -> str:
        """Código nos nomes dos arquivos baixados: “230” ou “230-filial231”."""
        return f"{self.codigo_dominio}-filial{self.codigo_filial}" if self.codigo_filial else str(self.codigo_dominio)

    @property
    def documento_formatado(self) -> str:
        return formatar_documento(self.cnpj_cpf) if self.cnpj_cpf else ""

    def e_automatico(self, campo: str) -> bool:
        return campo in (self.campos_automaticos or [])
