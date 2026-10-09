"""exportação automática por empresa (§6.5): opção na empresa; exportação marcada como automática e quando foi baixada

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-09 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "empresa", sa.Column("exportacao_automatica", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("exportacao", sa.Column("automatica", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("exportacao", sa.Column("baixado_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("exportacao", "baixado_em")
    op.drop_column("exportacao", "automatica")
    op.drop_column("empresa", "exportacao_automatica")
