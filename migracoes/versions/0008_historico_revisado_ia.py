"""lançamento do histórico já revisado pela IA (não pergunta de novo)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lancamento_historico",
        sa.Column("revisado_ia", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("lancamento_historico", "revisado_ia")
