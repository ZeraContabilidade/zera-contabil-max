"""aprovação automática configurável por empresa (limiar de confiança, padrão 90)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("empresa", sa.Column("limiar_aprovacao", sa.Integer(), server_default="90", nullable=False))


def downgrade() -> None:
    op.drop_column("empresa", "limiar_aprovacao")
