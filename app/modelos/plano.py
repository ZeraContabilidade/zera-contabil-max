from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modelos.base import Base


class ContaContabil(Base):
    """Conta do plano de contas de uma empresa (cada empresa tem o seu).

    Não é Auditavel linha a linha: o plano vem do Domínio em bloco, e cada importação
    fica registrada (tabela importacao + log) com o resumo do que mudou.
    """

    __tablename__ = "conta_contabil"
    __table_args__ = (
        UniqueConstraint("empresa_id", "reduzido"),
        CheckConstraint("tipo IN ('S', 'A')", name="tipo"),
        Index("ix_conta_contabil_empresa_classificacao", "empresa_id", "classificacao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"))
    reduzido: Mapped[int]  # código usado no lanctos.txt
    classificacao: Mapped[str] = mapped_column(String(30))  # só os dígitos: 11102000001
    classificacao_formatada: Mapped[str] = mapped_column(String(40))  # 1.1.1.02.000001
    descricao: Mapped[str] = mapped_column(String(120))
    tipo: Mapped[str] = mapped_column(String(1))  # S = sintética (grupo), A = analítica (recebe lançamento)
    nivel: Mapped[int]
    ativa: Mapped[bool] = mapped_column(default=True)  # False = saiu do plano na última importação

    @property
    def analitica(self) -> bool:
        return self.tipo == "A"

    @property
    def rotulo(self) -> str:
        """Como a conta aparece nas telas: '355 – ÁGUA E ESGOTO'."""
        return f"{self.reduzido} – {self.descricao}"
