from alembic import context
from sqlalchemy import create_engine

from app.config import obter_config
from app.modelos import Base

target_metadata = Base.metadata


def rodar_offline() -> None:
    context.configure(url=obter_config().url_banco(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def rodar_online() -> None:
    engine = create_engine(obter_config().url_banco())
    with engine.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    rodar_offline()
else:
    rodar_online()
