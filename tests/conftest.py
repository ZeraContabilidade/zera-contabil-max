"""Os testes usam um banco separado (<nome>_teste) no mesmo PostgreSQL: os dados reais nunca são tocados."""

from scripts.banco_teste import criar_banco_teste, esvaziar_tabelas, usar_banco_teste

URL_TESTE = usar_banco_teste()  # antes de importar o sistema

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import gerar_hash  # noqa: E402
from app.db import aplicar_migracoes, fabrica_sessoes  # noqa: E402
from app.main import app  # noqa: E402
from app.modelos import Papel, Usuario  # noqa: E402

SENHA_TESTE = "senha-de-teste-123"


@pytest.fixture(autouse=True)
def _sem_internet(monkeypatch):
    """Nenhum teste consulta a internet: a consulta pública do CNPJ responde "fora do ar".
    Testes que precisam de dados usam `cnpj_responde` com uma resposta gravada."""
    monkeypatch.setattr("app.servicos.cnpj_publico._buscar_http", lambda cnpj: None)


@pytest.fixture
def cnpj_responde(monkeypatch):
    def _responder(resposta: dict | None):
        consultados = []

        def _falso(cnpj):
            consultados.append(cnpj)
            return resposta

        monkeypatch.setattr("app.servicos.cnpj_publico._buscar_http", _falso)
        return consultados

    return _responder


@pytest.fixture(scope="session")
def _banco_teste_pronto() -> bool:
    if not criar_banco_teste(URL_TESTE):
        return False
    aplicar_migracoes()
    return True


@pytest.fixture
def banco(_banco_teste_pronto):
    """Banco de teste vazio. Pula o teste se o PostgreSQL estiver desligado."""
    if not _banco_teste_pronto:
        pytest.skip("PostgreSQL desligado — rode o INICIAR.bat (ou 'docker compose up -d') antes dos testes")
    esvaziar_tabelas()


@pytest.fixture
def sessao(banco):
    with fabrica_sessoes()() as s:
        yield s


@pytest.fixture
def cliente():
    return TestClient(app)


@pytest.fixture
def criar_usuario(sessao):
    def _criar(login="ana", papel=Papel.SUPERVISOR, nome=None, ativo=True, senha=SENHA_TESTE) -> Usuario:
        usuario = Usuario(
            nome=nome or login.capitalize(),
            login=login,
            senha_hash=gerar_hash(senha),
            papel=papel,
            ativo=ativo,
        )
        sessao.add(usuario)
        sessao.commit()
        return usuario

    return _criar


def entrar(cliente: TestClient, login: str, senha: str = SENHA_TESTE):
    return cliente.post("/login", data={"login": login, "senha": senha}, follow_redirects=False)
