"""fornecedores a cadastrar no Domínio (empresas com conta individual por fornecedor)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-08 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fornecedor_a_cadastrar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("chave", sa.String(length=200), nullable=False),
        sa.Column("cnpj_cpf", sa.String(length=14), nullable=True),
        sa.Column("grupo", sa.String(length=40), nullable=True),
        sa.Column("origem", sa.String(length=10), nullable=False),
        sa.Column("situacao", sa.String(length=12), nullable=False),
        sa.Column("conta_id", sa.Integer(), nullable=True),
        sa.Column("justificativa", sa.Text(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolvido_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conta_id"], ["conta_contabil.id"], name=op.f("fk_fornecedor_a_cadastrar_conta_id_conta_contabil")
        ),
        sa.ForeignKeyConstraint(
            ["empresa_id"], ["empresa.id"], name=op.f("fk_fornecedor_a_cadastrar_empresa_id_empresa")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fornecedor_a_cadastrar")),
        sa.UniqueConstraint("empresa_id", "chave", name=op.f("uq_fornecedor_a_cadastrar_empresa_id")),
    )
    op.create_index(
        op.f("ix_fornecedor_a_cadastrar_empresa_id"), "fornecedor_a_cadastrar", ["empresa_id"], unique=False
    )
    op.add_column("sugestao", sa.Column("fornecedor_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sugestao_fornecedor_id_fornecedor_a_cadastrar"),
        "sugestao",
        "fornecedor_a_cadastrar",
        ["fornecedor_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_sugestao_fornecedor_id_fornecedor_a_cadastrar"), "sugestao", type_="foreignkey")
    op.drop_column("sugestao", "fornecedor_id")
    op.drop_index(op.f("ix_fornecedor_a_cadastrar_empresa_id"), table_name="fornecedor_a_cadastrar")
    op.drop_table("fornecedor_a_cadastrar")
