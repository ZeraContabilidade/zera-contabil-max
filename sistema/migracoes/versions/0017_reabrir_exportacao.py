"""reabertura da exportação pelo Supervisor (quem, quando, motivo)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-08 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("exportacao", sa.Column("reaberta_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("exportacao", sa.Column("reaberta_por_id", sa.Integer(), nullable=True))
    op.add_column("exportacao", sa.Column("motivo_reabertura", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_exportacao_reaberta_por_id_usuario"), "exportacao", "usuario", ["reaberta_por_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_exportacao_reaberta_por_id_usuario"), "exportacao", type_="foreignkey")
    op.drop_column("exportacao", "motivo_reabertura")
    op.drop_column("exportacao", "reaberta_por_id")
    op.drop_column("exportacao", "reaberta_em")
