from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# nomes previsíveis para índices e restrições (as migrações ficam estáveis)
CONVENCAO_NOMES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO_NOMES)


class Auditavel:
    """Modelos com esta marca têm toda inclusão, alteração e exclusão gravada no log (app/auditoria.py)."""

    campos_sigilosos: tuple[str, ...] = ()  # aparecem como *** no log
    campos_nao_auditados: tuple[str, ...] = ()  # mudanças nesses campos não geram log
