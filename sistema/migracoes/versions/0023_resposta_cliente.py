"""perguntas ao cliente: a resposta do cliente em cada linha da Revisão

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-13 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sugestao", sa.Column("resposta_cliente", sa.String(length=200), nullable=True))
    op.add_column("sugestao", sa.Column("resposta_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sugestao", "resposta_em")
    op.drop_column("sugestao", "resposta_cliente")
