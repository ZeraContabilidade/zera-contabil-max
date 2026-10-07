"""empresas

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 13:38:55.011012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # busca sem ligar para acentos ("crianca" acha "CRIANÇA"); vem junto com o PostgreSQL
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.create_table(
        "empresa",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo_dominio", sa.Integer(), nullable=False),
        sa.Column("razao_social", sa.String(length=200), nullable=True),
        sa.Column("nome_curto", sa.String(length=80), nullable=True),
        sa.Column("cnpj_cpf", sa.String(length=14), nullable=True),
        # o Enum cria sozinho a restrição ck_empresa_regime
        sa.Column(
            "regime",
            sa.Enum(
                "SIMPLES",
                "PRESUMIDO",
                "REAL",
                "MEI",
                "TERCEIRO_SETOR",
                "OUTRO",
                name="regime",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("responsavel_id", sa.Integer(), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("modelo_complemento", sa.String(length=200), nullable=False),
        sa.Column("ativa", sa.Boolean(), nullable=False),
        sa.Column("campos_automaticos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dados_publicos", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["responsavel_id"], ["usuario.id"], name=op.f("fk_empresa_responsavel_id_usuario")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_empresa")),
        sa.UniqueConstraint("cnpj_cpf", name=op.f("uq_empresa_cnpj_cpf")),
        sa.UniqueConstraint("codigo_dominio", name=op.f("uq_empresa_codigo_dominio")),
    )


def downgrade() -> None:
    op.drop_table("empresa")
