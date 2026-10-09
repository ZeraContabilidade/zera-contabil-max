"""sugestão conferida pelo usuário na Revisão (quem e quando)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sugestao", sa.Column("conferido_por_id", sa.Integer(), nullable=True))
    op.add_column("sugestao", sa.Column("conferido_em", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_sugestao_conferido_por_id_usuario"), "sugestao", "usuario", ["conferido_por_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_sugestao_conferido_por_id_usuario"), "sugestao", type_="foreignkey")
    op.drop_column("sugestao", "conferido_em")
    op.drop_column("sugestao", "conferido_por_id")
