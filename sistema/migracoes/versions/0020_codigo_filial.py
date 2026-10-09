"""código da filial na empresa (campo 8 do lanctos.txt); cada filial é um cadastro com o código da matriz repetido

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-09 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("empresa", sa.Column("codigo_filial", sa.Integer(), nullable=True))
    op.drop_constraint(op.f("uq_empresa_codigo_dominio"), "empresa", type_="unique")
    op.create_unique_constraint(
        op.f("uq_empresa_codigo_dominio"),
        "empresa",
        ["codigo_dominio", "codigo_filial"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_empresa_codigo_dominio"), "empresa", type_="unique")
    op.create_unique_constraint(op.f("uq_empresa_codigo_dominio"), "empresa", ["codigo_dominio"])
    op.drop_column("empresa", "codigo_filial")
