"""Aviso de extrato faltando: conta que teve extrato no mês anterior e não neste, e extrato que não chega ao fim do
mês — só em meses que já terminaram."""

from dataclasses import replace
from datetime import date

import pytest

from app.servicos.extratos import extratos_faltando, importar_extrato
from tests.test_revisao import AGOSTO, SETEMBRO, empresa  # noqa: F401 — empresa de teste com o extrato de agosto

pytestmark = pytest.mark.banco
SETEMBRO_1, OUTUBRO_1 = date(2026, 9, 1), date(2026, 10, 1)


@pytest.fixture(autouse=True)
def hoje_13_de_outubro(monkeypatch):
    monkeypatch.setattr("app.servicos.extratos.hoje", lambda: date(2026, 10, 13))


def test_falta_o_extrato_da_conta_que_teve_no_mes_anterior(sessao, empresa):  # noqa: F811
    assert extratos_faltando(sessao, empresa, AGOSTO) == []  # agosto completo (e sem mês anterior)
    faltas = extratos_faltando(sessao, empresa, SETEMBRO_1)
    assert [f.texto for f in faltas] == [
        "Banco do Brasil · ag. 1234-5 · conta corrente 12345-6 — setembro/2026: sem extrato (teve em agosto/2026)"
    ]
    assert extratos_faltando(sessao, empresa, OUTUBRO_1) == []  # outubro ainda não terminou: é normal faltar


def test_extrato_que_nao_chega_ao_fim_do_mes(sessao, empresa, monkeypatch):  # noqa: F811
    metade = replace(SETEMBRO, fim=date(2026, 9, 20))
    monkeypatch.setattr("app.servicos.extratos.ler_extrato", lambda nome, conteudo: metade)
    importar_extrato(sessao, empresa, "setembro-parcial.pdf", b"%PDF-parcial", None)
    sessao.commit()
    assert [f.motivo for f in extratos_faltando(sessao, empresa, SETEMBRO_1)] == ["o extrato vai só até 20/09"]


def test_avisos_na_aba_no_cartao_e_no_painel(cliente, empresa):  # noqa: F811
    aba = cliente.get(f"/empresas/{empresa.id}", params={"aba": "extratos", "mes": "2026-09"}).text
    assert "Falta 1 extrato(s):" in aba and "sem extrato (teve em agosto/2026)" in aba
    assert "⚠ falta 1 extrato(s)" in cliente.get("/", params={"mes": "2026-09"}).text
    assert "⚠ falta 1 extrato(s)" in cliente.get("/painel", params={"mes": "2026-09"}).text
    assert "falta" not in cliente.get("/", params={"mes": "2026-08"}).text.split("Creche Teste")[1][:400]
