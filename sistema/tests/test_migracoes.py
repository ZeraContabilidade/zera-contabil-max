import pytest
from alembic import command

from app.db import config_alembic

pytestmark = pytest.mark.banco


def test_migracoes_batem_com_os_modelos(banco):
    """Falha se alguém mudou um modelo e esqueceu de criar a migração."""
    command.check(config_alembic())
