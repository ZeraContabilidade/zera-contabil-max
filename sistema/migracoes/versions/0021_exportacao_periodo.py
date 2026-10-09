"""exportação de um período (de um mês até outro): último mês da exportação

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-09 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("exportacao", sa.Column("competencia_fim", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("exportacao", "competencia_fim")
