"""Busca rápida (Ctrl+K) e atalhos do teclado: a lista do que dá para abrir e a moldura que liga tudo."""

import pytest

from app.modelos import Empresa, Papel
from tests.conftest import entrar

pytestmark = pytest.mark.banco


def test_lista_empresas_ativas_no_proximo_passo_e_telas_do_supervisor(cliente, criar_usuario, sessao):
    criar_usuario("ana")
    entrar(cliente, "ana")
    sessao.add_all(
        [
            Empresa(codigo_dominio=230, nome_curto="Casa Criança", razao_social="CASA CRIANCA ESPERANCA"),
            Empresa(codigo_dominio=230, codigo_filial=231, nome_curto="Casa Criança Norte"),
            Empresa(codigo_dominio=410, nome_curto="Padaria Antiga", ativa=False),
        ]
    )
    sessao.commit()
    dados = cliente.get("/atalhos").json()
    nomes = {e["nome"]: e for e in dados["empresas"]}
    assert set(nomes) == {"Casa Criança", "Casa Criança Norte"}  # a inativa não aparece
    assert nomes["Casa Criança"]["aba"] == "plano" and nomes["Casa Criança"]["proximo"] == "Próximo: Plano"
    assert nomes["Casa Criança"]["outro_nome"] == "CASA CRIANCA ESPERANCA"
    assert nomes["Casa Criança Norte"]["detalhe"] == "código 230 · filial 231"
    assert [a["aba"] for a in dados["abas"]] == ["plano", "aprendizado", "extratos", "revisao", "exportar", "cadastro"]
    assert {"Painel do Supervisor", "Usuários", "Nova empresa"} <= {t["nome"] for t in dados["telas"]}


def test_assistente_nao_ve_telas_do_supervisor(cliente, criar_usuario):
    criar_usuario("bia", papel=Papel.ASSISTENTE)
    entrar(cliente, "bia")
    telas = {t["nome"] for t in cliente.get("/atalhos").json()["telas"]}
    assert "Empresas" in telas and "Minha senha" in telas
    assert not telas & {"Painel do Supervisor", "Usuários", "Log", "Nova empresa"}


def test_sem_login_nao_entrega_a_lista(cliente):
    resposta = cliente.get("/atalhos", follow_redirects=False)
    assert resposta.status_code in (302, 303) and "/login" in resposta.headers["location"]


def test_moldura_tem_busca_rapida_e_atalhos(cliente, criar_usuario):
    criar_usuario("ana")
    entrar(cliente, "ana")
    tela = cliente.get("/").text
    assert "data-abrir-paleta" in tela and 'id="paleta"' in tela and 'id="atalhos-ajuda"' in tela
    assert "paleta.js" in tela and "Atalhos do teclado" in tela
