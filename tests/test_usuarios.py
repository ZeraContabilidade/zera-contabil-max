import re

import pytest
from sqlalchemy import select

from app.modelos import Log, Papel, Usuario
from tests.conftest import entrar

pytestmark = pytest.mark.banco

NOVO = {
    "nome": "Carla Assistente",
    "login": "carla",
    "email": "Carla@Zera.com.br",
    "papel": "ASSISTENTE",
    "senha": "senha-da-carla",
    "confirmacao": "senha-da-carla",
}


@pytest.mark.parametrize("papel", [Papel.ASSISTENTE, Papel.CONTADOR])
def test_so_supervisor_ve_usuarios_e_log(cliente, criar_usuario, papel):
    criar_usuario("ana")
    criar_usuario("bia", papel=papel)
    entrar(cliente, "bia")
    for endereco in ("/usuarios", "/log", "/usuarios/1"):
        resposta = cliente.get(endereco)
        assert resposta.status_code == 403, endereco
        assert "Só o Supervisor" in resposta.text
    assert cliente.post("/usuarios", data=NOVO).status_code == 403


def test_supervisor_cadastra_usuario(cliente, criar_usuario, sessao):
    criar_usuario("ana")
    entrar(cliente, "ana")
    resposta = cliente.post("/usuarios", data=NOVO, follow_redirects=True)
    assert "Usuário Carla Assistente cadastrado" in resposta.text
    carla = sessao.scalar(select(Usuario).where(Usuario.login == "carla"))
    assert carla.email == "carla@zera.com.br"
    assert carla.papel == Papel.ASSISTENTE
    cliente.post("/sair")
    assert entrar(cliente, "carla", "senha-da-carla").status_code == 303


def test_cadastro_recusa_login_repetido_com_mensagem_clara(cliente, criar_usuario):
    criar_usuario("ana")
    entrar(cliente, "ana")
    resposta = cliente.post("/usuarios", data={**NOVO, "login": "ANA"})
    assert resposta.status_code == 400
    assert "O usuário “ana” já está em uso" in resposta.text


def test_cadastro_recusa_email_incompleto(cliente, criar_usuario):
    criar_usuario("ana")
    entrar(cliente, "ana")
    resposta = cliente.post("/usuarios", data={**NOVO, "email": "carla@"})
    assert "e-mail parece incompleto" in resposta.text


def test_nao_deixa_o_sistema_sem_supervisor(cliente, criar_usuario, sessao):
    ana = criar_usuario("ana", nome="Ana")
    entrar(cliente, "ana")
    resposta = cliente.post(
        f"/usuarios/{ana.id}", data={"nome": "Ana", "email": "", "papel": "CONTADOR", "ativo": "on"}
    )
    assert resposta.status_code == 400
    assert "pelo menos um Supervisor ativo" in resposta.text
    resposta = cliente.post(f"/usuarios/{ana.id}", data={"nome": "Ana", "email": "", "papel": "SUPERVISOR"})
    assert "pelo menos um Supervisor ativo" in resposta.text
    sessao.refresh(ana)
    assert ana.papel == Papel.SUPERVISOR and ana.ativo


def test_supervisor_redefine_senha_e_derruba_login_aberto(criar_usuario, cliente):
    from fastapi.testclient import TestClient

    from app.main import app

    criar_usuario("ana")
    bia = criar_usuario("bia", papel=Papel.ASSISTENTE)
    navegador_da_bia = TestClient(app)
    entrar(navegador_da_bia, "bia")
    assert navegador_da_bia.get("/", follow_redirects=False).status_code == 200

    entrar(cliente, "ana")
    cliente.post(f"/usuarios/{bia.id}/senha", data={"senha": "nova-da-bia", "confirmacao": "nova-da-bia"})

    assert navegador_da_bia.get("/", follow_redirects=False).status_code == 303
    assert entrar(navegador_da_bia, "bia", "nova-da-bia").status_code == 303


def test_auditoria_registra_quem_alterou_antes_e_depois_sem_mostrar_senha(cliente, criar_usuario, sessao):
    ana = criar_usuario("ana")
    entrar(cliente, "ana")
    cliente.post("/usuarios", data=NOVO)
    carla = sessao.scalar(select(Usuario).where(Usuario.login == "carla"))
    cliente.post(
        f"/usuarios/{carla.id}", data={"nome": "Carla Souza", "email": "", "papel": "CONTADOR", "ativo": "on"}
    )

    criacao = sessao.scalar(select(Log).where(Log.acao == "CRIAR", Log.entidade_id == str(carla.id)))
    assert criacao.usuario_id == ana.id
    assert criacao.entidade == "usuario"
    assert criacao.depois["login"] == "carla"
    assert criacao.depois["senha_hash"] == "***"

    alteracao = sessao.scalar(select(Log).where(Log.acao == "ALTERAR", Log.entidade_id == str(carla.id)))
    assert alteracao.usuario_id == ana.id
    assert alteracao.antes == {
        "nome": "Carla Assistente",
        "email": "carla@zera.com.br",
        "papel": "ASSISTENTE",
    }
    assert alteracao.depois == {"nome": "Carla Souza", "email": None, "papel": "CONTADOR"}

    tela = cliente.get("/log").text
    assert "Carla Souza" in tela and "Alterou" in tela
    assert "Usuário nº" in tela
    assert re.search(r"<strong>Senha</strong>:\s*\*\*\*", tela)
    assert "True" not in tela and "None" not in tela  # aparece "Sim" / "—", não termos de programação


def test_ultimo_acesso_nao_enche_o_log(cliente, criar_usuario, sessao):
    criar_usuario("ana")
    entrar(cliente, "ana")
    entrar(cliente, "ana")
    assert sessao.scalar(select(Log).where(Log.acao == "ALTERAR")) is None
