"""pasta de entrada: a pasta onde o cliente deixa os extratos (o sistema só lê) e o que a busca já olhou

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-13 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("empresa", sa.Column("pasta_extratos", sa.String(length=400), nullable=True))
    op.create_table(
        "arquivo_pasta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("caminho", sa.String(length=500), nullable=False),
        sa.Column("tamanho", sa.Integer(), nullable=False),
        sa.Column("modificado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("resultado", sa.String(length=12), nullable=False),
        sa.Column("detalhe", sa.Text(), nullable=True),
        sa.Column("quando", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], name=op.f("fk_arquivo_pasta_empresa_id_empresa")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_arquivo_pasta")),
        sa.UniqueConstraint("empresa_id", "caminho", name=op.f("uq_arquivo_pasta_empresa_id")),
    )
    op.create_index(op.f("ix_arquivo_pasta_empresa_id"), "arquivo_pasta", ["empresa_id"], unique=False)
    op.create_index(op.f("ix_arquivo_pasta_sha256"), "arquivo_pasta", ["sha256"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_arquivo_pasta_sha256"), table_name="arquivo_pasta")
    op.drop_index(op.f("ix_arquivo_pasta_empresa_id"), table_name="arquivo_pasta")
    op.drop_table("arquivo_pasta")
    op.drop_column("empresa", "pasta_extratos")
