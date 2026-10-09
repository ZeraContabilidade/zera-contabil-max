"""lançamento do histórico com um lado só (Diário impresso só com algumas contas)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("lancamento_historico", "conta_debito_id", nullable=True)
    op.alter_column("lancamento_historico", "conta_credito_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM lancamento_historico WHERE conta_debito_id IS NULL OR conta_credito_id IS NULL")
    op.alter_column("lancamento_historico", "conta_credito_id", nullable=False)
    op.alter_column("lancamento_historico", "conta_debito_id", nullable=False)
