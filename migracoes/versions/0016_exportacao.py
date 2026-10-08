"""exportação do lanctos.txt (registro) + sugestão ligada à exportação que a travou

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-08 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exportacao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("competencia", sa.Date(), nullable=False),
        sa.Column("contas_bancarias", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("linhas", sa.Integer(), nullable=False),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("deixadas_de_fora", sa.Integer(), nullable=False),
        sa.Column("arquivo_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["arquivo_id"], ["arquivo_original.id"], name=op.f("fk_exportacao_arquivo_id_arquivo_original")
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], name=op.f("fk_exportacao_empresa_id_empresa")),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], name=op.f("fk_exportacao_usuario_id_usuario")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exportacao")),
    )
    op.create_index(op.f("ix_exportacao_empresa_id"), "exportacao", ["empresa_id"], unique=False)
    op.add_column("sugestao", sa.Column("exportacao_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_sugestao_exportacao_id"), "sugestao", ["exportacao_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_sugestao_exportacao_id_exportacao"), "sugestao", "exportacao", ["exportacao_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_sugestao_exportacao_id_exportacao"), "sugestao", type_="foreignkey")
    op.drop_index(op.f("ix_sugestao_exportacao_id"), table_name="sugestao")
    op.drop_column("sugestao", "exportacao_id")
    op.drop_index(op.f("ix_exportacao_empresa_id"), table_name="exportacao")
    op.drop_table("exportacao")
