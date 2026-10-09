"""arquivo apagado depois dos 5 anos de guarda (o registro fica)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-08 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("arquivo_original", sa.Column("excluido_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("arquivo_original", "excluido_em")
