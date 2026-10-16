"""unidade (creche) na empresa: creches que dividem o código, o CNPJ e o plano no Domínio viram cadastros separados

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-15 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("empresa", sa.Column("unidade", sa.String(length=60), nullable=True))
    op.drop_constraint(op.f("uq_empresa_codigo_dominio"), "empresa", type_="unique")
    op.create_unique_constraint(
        op.f("uq_empresa_codigo_dominio"),
        "empresa",
        ["codigo_dominio", "codigo_filial", "unidade"],
        postgresql_nulls_not_distinct=True,
    )
    op.drop_constraint(op.f("uq_empresa_cnpj_cpf"), "empresa", type_="unique")
    op.create_index(
        "uq_empresa_cnpj_cpf_unidade",
        "empresa",
        ["cnpj_cpf", sa.text("coalesce(unidade, '')")],
        unique=True,
        postgresql_where=sa.text("cnpj_cpf IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_empresa_cnpj_cpf_unidade", table_name="empresa")
    op.create_unique_constraint(op.f("uq_empresa_cnpj_cpf"), "empresa", ["cnpj_cpf"])
    op.drop_constraint(op.f("uq_empresa_codigo_dominio"), "empresa", type_="unique")
    op.create_unique_constraint(
        op.f("uq_empresa_codigo_dominio"),
        "empresa",
        ["codigo_dominio", "codigo_filial"],
        postgresql_nulls_not_distinct=True,
    )
    op.drop_column("empresa", "unidade")
