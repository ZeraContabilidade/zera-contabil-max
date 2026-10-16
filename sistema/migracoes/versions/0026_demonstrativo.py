"""demonstrativo da prestação de contas: linhas ligadas ao extrato e movimento desdobrado (rateio das guias)

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-16 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("movimento_extrato", sa.Column("desdobrado", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("movimento_extrato", sa.Column("parte_de_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_movimento_extrato_parte_de_id_movimento_extrato"),
        "movimento_extrato",
        "movimento_extrato",
        ["parte_de_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_movimento_extrato_parte_de_id"), "movimento_extrato", ["parte_de_id"])
    op.create_table(
        "linha_demonstrativo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("importacao_id", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Date(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("sentido", sa.String(length=8), nullable=False),
        sa.Column("valor", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("favorecido", sa.String(length=200), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("cnpj_cpf", sa.String(length=14), nullable=True),
        sa.Column("especificacao", sa.String(length=200), nullable=False),
        sa.Column("grupo", sa.String(length=60), nullable=False),
        sa.Column("item", sa.Integer(), nullable=True),
        sa.Column("documento_tipo", sa.String(length=30), nullable=False),
        sa.Column("documento_numero", sa.String(length=40), nullable=False),
        sa.Column("documento_data", sa.Date(), nullable=True),
        sa.Column("transferencia", sa.String(length=40), nullable=False),
        sa.Column("data", sa.Date(), nullable=True),
        sa.Column("conta_bancaria_id", sa.Integer(), nullable=True),
        sa.Column("movimento_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["conta_bancaria_id"],
            ["conta_bancaria.id"],
            name=op.f("fk_linha_demonstrativo_conta_bancaria_id_conta_bancaria"),
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], name=op.f("fk_linha_demonstrativo_empresa_id_empresa")),
        sa.ForeignKeyConstraint(
            ["importacao_id"], ["importacao.id"], name=op.f("fk_linha_demonstrativo_importacao_id_importacao")
        ),
        sa.ForeignKeyConstraint(
            ["movimento_id"],
            ["movimento_extrato.id"],
            name=op.f("fk_linha_demonstrativo_movimento_id_movimento_extrato"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_linha_demonstrativo")),
        sa.UniqueConstraint("movimento_id", name=op.f("uq_linha_demonstrativo_movimento_id")),
    )
    op.create_index(op.f("ix_linha_demonstrativo_empresa_id"), "linha_demonstrativo", ["empresa_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_linha_demonstrativo_empresa_id"), table_name="linha_demonstrativo")
    op.drop_table("linha_demonstrativo")
    op.drop_index(op.f("ix_movimento_extrato_parte_de_id"), table_name="movimento_extrato")
    op.drop_constraint(
        op.f("fk_movimento_extrato_parte_de_id_movimento_extrato"), "movimento_extrato", type_="foreignkey"
    )
    op.drop_column("movimento_extrato", "parte_de_id")
    op.drop_column("movimento_extrato", "desdobrado")
