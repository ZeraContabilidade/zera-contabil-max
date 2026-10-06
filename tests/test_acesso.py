import pytest
from sqlalchemy import select

from app.auth import gerar_hash, senha_confere
from app.modelos import Log, Papel, Usuario
from tests.conftest import SENHA_TESTE, entrar

pytestmark = pytest.mark.banco


def test_senha_guardada_so_como_hash_e_conferida():
    senha_hash = gerar_hash("minha-senha-1")
    assert "minha-senha-1" not in senha_hash
    assert senha_confere(senha_hash, "minha-senha-1")
    assert not senha_confere(senha_hash, "outra-senha")
    assert not senha_confere("hash-estragado", "minha-senha-1")


def test_sem_usuarios_o_sistema_pede_o_primeiro_acesso(cliente, banco):
    resposta = cliente.get("/", follow_redirects=True)
    assert "Primeiro acesso" in resposta.text


def test_primeiro_acesso_cria_supervisor_e_ja_entra(cliente, sessao):
    resposta = cliente.post(
        "/primeiro-acesso",
        data={
            "nome": "Maria Supervisora",
            "login": " Maria.Silva ",
            "email": "",
            "senha": "senha-forte-1",
            "confirmacao": "senha-forte-1",
        },
        follow_redirects=True,
    )
    assert "Nenhuma empresa cadastrada ainda" in resposta.text
    assert "Maria Supervisora" in resposta.text  # nome no menu do topo
    usuario = sessao.scalar(select(Usuario))
    assert usuario.login == "maria.silva"
    assert usuario.papel == Papel.SUPERVISOR
    assert usuario.senha_hash != "senha-forte-1"


def test_primeiro_acesso_some_depois_que_existe_usuario(cliente, criar_usuario):
    criar_usuario("ana")
    resposta = cliente.post(
        "/primeiro-acesso",
        data={"nome": "Intruso", "login": "intruso", "senha": "12345678", "confirmacao": "12345678"},
        follow_redirects=False,
    )
    assert resposta.headers["location"] == "/login"


def test_primeiro_acesso_explica_senha_curta_e_diferente(cliente, banco):
    dados = {"nome": "Maria", "login": "maria", "senha": "123", "confirmacao": "123"}
    assert "pelo menos 8 caracteres" in cliente.post("/primeiro-acesso", data=dados).text
    dados.update(senha="senha-forte-1", confirmacao="senha-forte-2")
    assert "não são iguais" in cliente.post("/primeiro-acesso", data=dados).text


def test_pagina_protegida_manda_para_o_login_e_volta_depois(cliente, criar_usuario):
    criar_usuario("ana")
    resposta = cliente.get("/usuarios", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/login?proximo=/usuarios"

    resposta = cliente.post(
        "/login", data={"login": "ana", "senha": SENHA_TESTE, "proximo": "/usuarios"}, follow_redirects=False
    )
    assert resposta.headers["location"] == "/usuarios"


def test_login_nao_redireciona_para_outro_site(cliente, criar_usuario):
    criar_usuario("ana")
    resposta = cliente.post(
        "/login",
        data={"login": "ana", "senha": SENHA_TESTE, "proximo": "//site-malicioso.com"},
        follow_redirects=False,
    )
    assert resposta.headers["location"] == "/"


def test_login_aceita_maiusculas_e_email(cliente, criar_usuario, sessao):
    usuario = criar_usuario("ana")
    usuario.email = "ana@zera.com.br"
    sessao.commit()
    assert entrar(cliente, "  ANA ").status_code == 303
    cliente.post("/sair")
    assert entrar(cliente, "Ana@Zera.com.br").status_code == 303


def test_senha_errada_avisa_e_fica_no_log(cliente, criar_usuario, sessao):
    criar_usuario("ana")
    resposta = entrar(cliente, "ana", "senha-errada")
    assert resposta.status_code == 400
    assert "Usuário ou senha incorretos" in resposta.text
    log = sessao.scalar(select(Log).where(Log.acao == "LOGIN_FALHOU"))
    assert "ana" in log.detalhe


def test_login_e_saida_ficam_no_log_com_quem_fez(cliente, criar_usuario, sessao):
    ana = criar_usuario("ana")
    entrar(cliente, "ana")
    cliente.post("/sair")
    acoes = [(log.acao, log.usuario_id) for log in sessao.scalars(select(Log).order_by(Log.id))]
    assert ("LOGIN", ana.id) in acoes
    assert ("LOGOUT", ana.id) in acoes
    assert cliente.get("/", follow_redirects=False).status_code == 303  # saiu de verdade


def test_usuario_inativo_nao_entra(cliente, criar_usuario):
    criar_usuario("ana")
    criar_usuario("bia", papel=Papel.ASSISTENTE, ativo=False)
    assert entrar(cliente, "bia").status_code == 400


def test_usuario_desativado_e_desconectado_na_hora(cliente, criar_usuario, sessao):
    criar_usuario("ana")
    bia = criar_usuario("bia", papel=Papel.ASSISTENTE)
    entrar(cliente, "bia")
    assert cliente.get("/", follow_redirects=False).status_code == 200
    bia.ativo = False
    sessao.commit()
    assert cliente.get("/", follow_redirects=False).status_code == 303


def test_trocar_minha_senha(cliente, criar_usuario):
    criar_usuario("bia", papel=Papel.ASSISTENTE)
    entrar(cliente, "bia")
    errada = cliente.post(
        "/minha-senha", data={"senha_atual": "xxx", "senha": "nova-senha-1", "confirmacao": "nova-senha-1"}
    )
    assert "senha atual não confere" in errada.text
    cliente.post(
        "/minha-senha",
        data={"senha_atual": SENHA_TESTE, "senha": "nova-senha-1", "confirmacao": "nova-senha-1"},
    )
    assert cliente.get("/", follow_redirects=False).status_code == 200  # continua logada
    cliente.post("/sair")
    assert entrar(cliente, "bia", SENHA_TESTE).status_code == 400
    assert entrar(cliente, "bia", "nova-senha-1").status_code == 303


def test_requisicao_htmx_sem_login_recebe_redirecionamento_htmx(cliente, criar_usuario):
    criar_usuario("ana")
    resposta = cliente.get("/usuarios", headers={"HX-Request": "true"}, follow_redirects=False)
    assert resposta.headers["HX-Redirect"] == "/login?proximo=/usuarios"
