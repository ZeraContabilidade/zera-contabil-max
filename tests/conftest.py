import pytest
from fastapi.testclient import TestClient

from app.db import banco_disponivel
from app.main import app


@pytest.fixture
def cliente():
    return TestClient(app)


@pytest.fixture
def banco():
    """Para testes que precisam do PostgreSQL rodando no Docker."""
    if not banco_disponivel():
        pytest.skip("PostgreSQL desligado — rode o INICIAR.bat (ou 'docker compose up -d') antes dos testes")
