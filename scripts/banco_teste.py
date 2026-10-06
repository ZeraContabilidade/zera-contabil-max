"""Banco separado (<nome>_teste) para os testes automáticos e o servidor de teste.

Os dados reais nunca são tocados. Chame `usar_banco_teste()` antes de qualquer
uso de `app.db` / `app.main`, porque a configuração fica guardada depois de lida.
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

from app.config import Config


def usar_banco_teste() -> URL:
    real = make_url(Config(database_url="").url_banco())
    url = real.set(database=f"{real.database}_teste")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    return url


def criar_banco_teste(url: URL) -> bool:
    """Cria o banco de teste se ainda não existir. Devolve False se o PostgreSQL estiver desligado."""
    administrador = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with administrador.connect() as conexao:
            existe = conexao.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :nome"), {"nome": url.database}
            )
            if not existe:
                conexao.execute(text(f'CREATE DATABASE "{url.database}"'))
        return True
    except OperationalError:
        return False
    finally:
        administrador.dispose()


def esvaziar_tabelas() -> None:
    from app.db import obter_engine
    from app.modelos import Base

    tabelas = ", ".join(tabela.name for tabela in Base.metadata.sorted_tables)
    with obter_engine().begin() as conexao:
        conexao.execute(text(f"TRUNCATE {tabelas} RESTART IDENTITY CASCADE"))
