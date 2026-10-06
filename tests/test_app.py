import re

import pytest

from tests.conftest import entrar


def test_css_js_logo_e_fonte_sao_servidos_localmente_sem_internet(cliente):
    for arquivo in (
        "vendor/pico.min.css",
        "vendor/htmx.min.js",
        "estilo.css",
        "tema.js",
        "marca/logo_escuro.png",
        "marca/logo_claro.png",
        "marca/emblema.png",
        "marca/Cinzel-Bold.ttf",
    ):
        assert cliente.get(f"/static/{arquivo}").status_code == 200, arquivo


def test_saude_responde_mesmo_sem_banco(cliente):
    resposta = cliente.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["sistema"] == "ok"


@pytest.mark.banco
def test_saude_mostra_banco_conectado(cliente, banco):
    assert cliente.get("/saude").json()["banco"] == "ok"


@pytest.mark.banco
def test_tela_de_entrada_tem_a_identidade_zera(cliente, criar_usuario):
    criar_usuario("ana")
    html = cliente.get("/login").text
    assert 'lang="pt-BR"' in html
    assert "marca/emblema.png" in html
    assert "Contábil MAX" in html
    assert re.search(r"/static/estilo\.css\?v=\d{9,}", html)  # versão no endereço evita CSS velho no cache


@pytest.mark.banco
def test_inicio_logado_mostra_logo_no_topo_e_nome(cliente, criar_usuario):
    criar_usuario("ana", nome="Ana Paula")
    entrar(cliente, "ana")
    html = cliente.get("/").text
    assert "marca/logo_escuro.png" in html and "marca/logo_claro.png" in html
    assert "Olá, Ana Paula!" in html
