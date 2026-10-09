"""Conexão com o PostgreSQL e migrações do banco."""

from collections.abc import Iterator
from functools import lru_cache

from alembic import command
from alembic.config import Config as ConfigAlembic
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.auditoria  # noqa: F401  (liga o log de auditoria em toda sessão de banco, em qualquer rotina)
from app.config import PASTA_SISTEMA, obter_config


@lru_cache
def obter_engine() -> Engine:
    return create_engine(
        obter_config().url_banco(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


@lru_cache
def fabrica_sessoes() -> sessionmaker[Session]:
    return sessionmaker(bind=obter_engine(), expire_on_commit=False)


def obter_sessao() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão de banco por requisição."""
    with fabrica_sessoes()() as sessao:
        yield sessao


def banco_disponivel() -> bool:
    try:
        with obter_engine().connect() as conexao:
            conexao.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def config_alembic() -> ConfigAlembic:
    return ConfigAlembic(str(PASTA_SISTEMA / "alembic.ini"))


def aplicar_migracoes() -> None:
    """Cria ou atualiza as tabelas do banco para a versão atual do sistema."""
    command.upgrade(config_alembic(), "head")
