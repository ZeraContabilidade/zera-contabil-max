"""usuarios e log

Revision ID: 0001
Revises:
Create Date: 2026-10-06 13:09:57.289893
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("login", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("senha_hash", sa.String(length=255), nullable=False),
        # o Enum cria sozinho a restrição ck_usuario_papel
        sa.Column(
            "papel",
            sa.Enum(
                "ASSISTENTE",
                "CONTADOR",
                "SUPERVISOR",
                name="papel",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ultimo_acesso", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuario")),
        sa.UniqueConstraint("email", name=op.f("uq_usuario_email")),
        sa.UniqueConstraint("login", name=op.f("uq_usuario_login")),
    )
    op.create_table(
        "log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("quando", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("acao", sa.String(length=30), nullable=False),
        sa.Column("entidade", sa.String(length=60), nullable=True),
        sa.Column("entidade_id", sa.String(length=60), nullable=True),
        sa.Column("antes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("depois", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detalhe", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], name=op.f("fk_log_usuario_id_usuario")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_log")),
    )
    op.create_index(op.f("ix_log_quando"), "log", ["quando"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_log_quando"), table_name="log")
    op.drop_table("log")
    op.drop_table("usuario")
