from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Auditavel, Base
from app.modelos.conta_chave import ContaChave
from app.modelos.importacao import ArquivoOriginal, Importacao
from app.modelos.plano import ContaContabil

TIPOS_CONTA = {"BANCO": "Conta corrente", "POUPANCA": "Poupança", "APLICACAO": "Aplicação"}


class ContaBancaria(Auditavel, Base):
    """Conta da empresa no banco, criada sozinha pelo primeiro extrato (§3.4).
    A conta contábil vem da conta-chave bancária (“BB conta 72637-0” → conta 8)."""

    __tablename__ = "conta_bancaria"
    __table_args__ = (UniqueConstraint("empresa_id", "banco_codigo", "numero", "tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    banco_codigo: Mapped[str] = mapped_column(String(3))  # 001 = Banco do Brasil
    banco_nome: Mapped[str] = mapped_column(String(60))
    agencia: Mapped[str] = mapped_column(String(20))
    numero: Mapped[str] = mapped_column(String(30))
    tipo: Mapped[str] = mapped_column(String(12))  # BANCO (conta corrente), POUPANCA ou APLICACAO
    titular: Mapped[str | None] = mapped_column(String(200))
    conta_chave_id: Mapped[int | None] = mapped_column(ForeignKey("conta_chave.id"))
    ativa: Mapped[bool] = mapped_column(default=True)
    # layout de planilha que esta conta usa: a próxima planilha igual vai direto para ela, sem perguntar
    assinatura_planilha: Mapped[str | None] = mapped_column(String(64))

    conta_chave: Mapped[ContaChave | None] = relationship()

    @property
    def rotulo(self) -> str:
        """'Banco do Brasil · ag. 2180-6 · conta corrente 72637-0'."""
        return f"{self.banco_nome} · ag. {self.agencia} · {TIPOS_CONTA.get(self.tipo, self.tipo).lower()} {self.numero}"


class Extrato(Base):
    """Um extrato importado: período, saldos e a conferência (saldo inicial + entradas − saídas = final)."""

    __tablename__ = "extrato"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    conta_bancaria_id: Mapped[int] = mapped_column(ForeignKey("conta_bancaria.id"))
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacao.id"))
    leitor: Mapped[str] = mapped_column(String(60))  # qual leitor entendeu o arquivo
    inicio: Mapped[date] = mapped_column(Date)
    fim: Mapped[date] = mapped_column(Date, index=True)
    saldo_inicial: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    saldo_final: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    saldo_cortado: Mapped[bool] = mapped_column(default=False)  # o PDF cortou os centavos do saldo
    entradas: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    saidas: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    conferencia: Mapped[str] = mapped_column(String(12))  # CONFERE, DIFERENCA ou SEM_SALDO
    diferenca: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conta_bancaria: Mapped[ContaBancaria] = relationship()
    importacao: Mapped[Importacao] = relationship()


class MovimentoExtrato(Base):
    """Uma linha do extrato. Importado em bloco (sem log linha a linha); o `hash` impede duplicar
    ao reimportar o mesmo extrato ou um período que se sobrepõe."""

    __tablename__ = "movimento_extrato"
    __table_args__ = (UniqueConstraint("conta_bancaria_id", "hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    conta_bancaria_id: Mapped[int] = mapped_column(ForeignKey("conta_bancaria.id"))
    extrato_id: Mapped[int] = mapped_column(ForeignKey("extrato.id"))
    ordem: Mapped[int]  # posição no extrato
    data: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # sempre positivo; o sentido diz se entrou ou saiu
    sentido: Mapped[str] = mapped_column(String(8))  # ENTRADA ou SAIDA
    historico: Mapped[str] = mapped_column(String(120))  # como o banco escreve: “Pagamento de Boleto”
    complemento: Mapped[str | None] = mapped_column(String(200))  # 2ª linha: favorecido ou pagador
    documento: Mapped[str | None] = mapped_column(String(60))
    codigo_banco: Mapped[str | None] = mapped_column(String(10))  # código do histórico no banco (BB: 109, 144...)
    hash: Mapped[str] = mapped_column(String(64))

    conta_bancaria: Mapped[ContaBancaria] = relationship()
    sugestao: Mapped["Sugestao | None"] = relationship(
        foreign_keys="Sugestao.movimento_id", back_populates="movimento", uselist=False
    )

    @property
    def descricao(self) -> str:
        return f"{self.historico} {self.complemento or ''}".strip()


class ModeloPlanilha(Auditavel, Base):
    """Colunas de um layout de planilha de extrato (Excel/CSV), confirmadas pelo usuário na 1ª vez (§3.4, §8).

    A assinatura é tirada dos títulos das colunas: a mesma planilha do mesmo banco tem a mesma assinatura,
    em qualquer empresa. `colunas` = {"data": 0, "historico": 2, "valor": 5, ...} (−1 = não tem)."""

    __tablename__ = "modelo_planilha_banco"

    id: Mapped[int] = mapped_column(primary_key=True)
    assinatura: Mapped[str] = mapped_column(String(64), unique=True)
    titulos: Mapped[list[str]] = mapped_column(JSONB, default=list)
    linha_titulos: Mapped[int]  # onde ficam os títulos (0 = primeira linha; −1 = planilha sem títulos)
    colunas: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    origem: Mapped[str] = mapped_column(String(10))  # TITULOS, IA ou USUARIO (quem achou as colunas)
    confirmado: Mapped[bool] = mapped_column(default=False)
    confirmado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


SITUACOES_FORNECEDOR = {"A_CADASTRAR": "A cadastrar", "CADASTRADO": "Cadastrado", "DESCARTADO": "Não é fornecedor"}


class FornecedorACadastrar(Auditavel, Base):
    """Fornecedor sem conta no plano de uma empresa com conta individual por fornecedor (§3.5, §6.2 passo 7).

    As linhas do extrato pagas a ele ficam pendentes até a conta existir: quando o plano é reimportado com uma
    conta nova de nome parecido (no grupo de fornecedores), ele sai da lista sozinho e as linhas recebem a conta."""

    __tablename__ = "fornecedor_a_cadastrar"
    __table_args__ = (UniqueConstraint("empresa_id", "chave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))  # nome sugerido para a conta no Domínio
    chave: Mapped[str] = mapped_column(String(200))  # nome normalizado (o mesmo fornecedor não entra duas vezes)
    cnpj_cpf: Mapped[str | None] = mapped_column(String(14))  # só quando está escrito no extrato
    grupo: Mapped[str | None] = mapped_column(String(40))  # onde criar a conta (ex.: 2.1.3.01)
    origem: Mapped[str] = mapped_column(String(10))  # IA ou USUARIO
    situacao: Mapped[str] = mapped_column(String(12), default="A_CADASTRAR")
    conta_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))  # a conta criada no Domínio
    justificativa: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conta: Mapped[ContaContabil | None] = relationship()


class Exportacao(Base):
    """Um lanctos.txt gerado (§3.6): quem, quando, mês, contas bancárias, quantas linhas e o arquivo (guardado 5 anos).

    As sugestões exportadas ficam EXPORTADO (travadas) e ligadas a esta exportação; só o Supervisor reabre (3.2).
    Não é Auditavel: a exportação inteira vira um evento no log."""

    __tablename__ = "exportacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    competencia: Mapped[date] = mapped_column(Date)  # 1º dia do mês exportado
    contas_bancarias: Mapped[list[int]] = mapped_column(JSONB, default=list)  # ids das contas escolhidas
    linhas: Mapped[int]
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    deixadas_de_fora: Mapped[int] = mapped_column(default=0)  # pendentes que ficaram de fora
    arquivo_id: Mapped[int] = mapped_column(ForeignKey("arquivo_original.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    arquivo: Mapped[ArquivoOriginal] = relationship()


STATUS_SUGESTAO = {
    "PENDENTE": "Pendente",
    "APROVADO": "Aprovado",
    "IGNORADO": "Sem lançamento",
    "EXPORTADO": "Exportado",
}


class Sugestao(Auditavel, Base):
    """Lançamento sugerido para um movimento do extrato (§6.2): débito, crédito, complemento, de onde veio.

    Feita em bloco pela classificação (sem log linha a linha); o que o usuário mudar depois é auditado.
    Verde (confiança ≥ 90) já vem APROVADO; IGNORADO = não gera lançamento (ex.: transferência entre
    contas da própria empresa que caem na mesma conta contábil)."""

    __tablename__ = "sugestao"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), index=True)
    movimento_id: Mapped[int] = mapped_column(ForeignKey("movimento_extrato.id"), unique=True)
    conta_debito_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))
    conta_credito_id: Mapped[int | None] = mapped_column(ForeignKey("conta_contabil.id"))
    complemento: Mapped[str] = mapped_column(String(300), default="")
    confianca: Mapped[int] = mapped_column(default=0)  # 0 a 100
    # REGRA (banco), TRANSFERENCIA, CNPJ, NOME, PALAVRA, VALOR, IA ou USUARIO
    origem: Mapped[str] = mapped_column(String(14))
    justificativa: Mapped[str | None] = mapped_column(Text)
    padrao_id: Mapped[int | None] = mapped_column(ForeignKey("padrao.id", ondelete="SET NULL"))
    par_id: Mapped[int | None] = mapped_column(ForeignKey("movimento_extrato.id"))  # a outra ponta da transferência
    status: Mapped[str] = mapped_column(String(10), default="PENDENTE")
    # a IA já olhou: não pergunta de novo
    revisado_ia: Mapped[bool] = mapped_column(default=False, server_default=false())
    # o usuário conferiu na Revisão (aprovou, corrigiu ou ignorou): a classificação automática e a IA não mexem mais
    conferido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    conferido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # pago a um fornecedor que ainda não tem conta: fica pendente (e a classificação não mexe) até a conta existir
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedor_a_cadastrar.id", ondelete="SET NULL"))
    exportacao_id: Mapped[int | None] = mapped_column(ForeignKey("exportacao.id"), index=True)  # EXPORTADO por ela
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    movimento: Mapped[MovimentoExtrato] = relationship(foreign_keys=[movimento_id], back_populates="sugestao")
    conta_debito: Mapped[ContaContabil | None] = relationship(foreign_keys=[conta_debito_id])
    conta_credito: Mapped[ContaContabil | None] = relationship(foreign_keys=[conta_credito_id])
    fornecedor: Mapped[FornecedorACadastrar | None] = relationship()

    campos_nao_auditados = ("atualizado_em",)

    @property
    def cor(self) -> str:
        """verde (alta), amarela (média) ou vermelha (pendente) — para a tela."""
        if self.status in ("IGNORADO", "APROVADO", "EXPORTADO"):
            return "verde" if self.status != "IGNORADO" else "cinza"
        return "amarela" if self.confianca >= 70 else "vermelha"
