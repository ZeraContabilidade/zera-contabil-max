"""Conexão com o PostgreSQL."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from app.config import obter_config


@lru_cache
def obter_engine() -> Engine:
    return create_engine(
        obter_config().url_banco(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


def banco_disponivel() -> bool:
    try:
        with obter_engine().connect() as conexao:
            conexao.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
