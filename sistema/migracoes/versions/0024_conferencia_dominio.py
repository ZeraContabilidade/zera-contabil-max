"""conferir com o Domínio: o saldo da conta banco no Domínio no fim do mês, digitado depois de importar

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-13 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conferencia_dominio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("conta_bancaria_id", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Date(), nullable=False),
        sa.Column("saldo_dominio", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("informado_por_id", sa.Integer(), nullable=True),
        sa.Column("informado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conta_bancaria_id"],
            ["conta_bancaria.id"],
            name=op.f("fk_conferencia_dominio_conta_bancaria_id_conta_bancaria"),
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], name=op.f("fk_conferencia_dominio_empresa_id_empresa")),
        sa.ForeignKeyConstraint(
            ["informado_por_id"], ["usuario.id"], name=op.f("fk_conferencia_dominio_informado_por_id_usuario")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conferencia_dominio")),
        sa.UniqueConstraint("conta_bancaria_id", "mes", name=op.f("uq_conferencia_dominio_conta_bancaria_id")),
    )
    op.create_index(op.f("ix_conferencia_dominio_empresa_id"), "conferencia_dominio", ["empresa_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_conferencia_dominio_empresa_id"), table_name="conferencia_dominio")
    op.drop_table("conferencia_dominio")
