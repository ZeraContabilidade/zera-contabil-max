from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Auditavel, Base
from app.modelos.plano import ContaContabil


class LancamentoHistorico(Base):
    """Lançamento já feito pelo escritório (lanctos.txt antigo, Diário ou Razão): a fonte do aprendizado (§6.1).

    Importado em bloco: cada importação fica em `importacao` + log; as linhas não são auditadas uma a uma.
    """

    __tablename__ = "lancamento_historico"
    __table_args__ = (UniqueConstraint("empresa_id", "marca"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacao.id"))
    data: Mapped[date] = mapped_column(Date, index=True)
    # um dos lados pode faltar: Diário impresso só com algumas contas (ex.: só o Passivo) mostra um lado só
    conta_debito_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))
    conta_credito_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    historico: Mapped[str] = mapped_column(Text)
    favorecido: Mapped[str | None] = mapped_column(String(200))
    cnpj_cpf: Mapped[str | None] = mapped_column(String(14))  # só quando o dígito confere
    natureza: Mapped[str | None] = mapped_column(String(200))
    documento: Mapped[str | None] = mapped_column(String(60))
    sentido: Mapped[str] = mapped_column(String(8))  # SAIDA (pagou pelo banco), ENTRADA (recebeu) ou OUTRO
    contrapartida_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))  # o lado que não é banco
    marca: Mapped[str] = mapped_column(String(64))  # impressão digital da linha: reimportar não duplica
    revisado_ia: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )  # a IA já viu: não pergunta de novo

    contrapartida: Mapped[ContaContabil | None] = relationship(foreign_keys=[contrapartida_id])


class Padrao(Auditavel, Base):
    """O que o sistema aprendeu: fornecedor/favorecido → conta, cliente → conta, palavra-chave → conta (§3.3).

    O aprendizado em bloco não gera uma linha de log por padrão (ver `auditoria_em_bloco`);
    as mudanças feitas pelo usuário (trocar conta, desativar, criar palavra) são auditadas.
    """

    __tablename__ = "padrao"
    __table_args__ = (UniqueConstraint("empresa_id", "tipo", "chave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(12))  # FORNECEDOR, CLIENTE ou PALAVRA
    chave: Mapped[str] = mapped_column(String(200))  # texto normalizado (sem acento, sem “de/da”, sem pontuação)
    nome: Mapped[str] = mapped_column(String(200))  # como aparece na tela
    cnpj_cpf: Mapped[str | None] = mapped_column(String(14))
    conta_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))
    natureza: Mapped[str | None] = mapped_column(String(200))  # a mais usada recentemente
    ocorrencias: Mapped[int] = mapped_column(default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    ultima_data: Mapped[date | None] = mapped_column(Date)
    ambiguo: Mapped[bool] = mapped_column(default=False)  # lançado em contas diferentes sem motivo claro
    ativo: Mapped[bool] = mapped_column(default=True)
    origem: Mapped[str] = mapped_column(String(10), default="APRENDIDO")  # APRENDIDO ou USUARIO
    # {"contas": [...], "por_natureza": {...}, "valores": [...]} — o resumo usado na classificação
    detalhes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    conta: Mapped[ContaContabil | None] = relationship()

    campos_nao_auditados = ("ocorrencias", "total", "ultima_data", "detalhes")
