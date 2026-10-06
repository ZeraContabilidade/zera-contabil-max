import pytest


def test_pagina_inicial_abre_com_o_nome_do_sistema(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "ZERA CONTÁBIL MAX" in resposta.text
    assert 'lang="pt-BR"' in resposta.text


def test_css_e_js_sao_servidos_localmente_sem_internet(cliente):
    assert cliente.get("/static/vendor/pico.min.css").status_code == 200
    assert cliente.get("/static/vendor/htmx.min.js").status_code == 200


def test_saude_responde_mesmo_sem_banco(cliente):
    resposta = cliente.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["sistema"] == "ok"


@pytest.mark.banco
def test_saude_mostra_banco_conectado(cliente, banco):
    assert cliente.get("/saude").json()["banco"] == "ok"
    assert "Banco de dados conectado" in cliente.get("/").text
