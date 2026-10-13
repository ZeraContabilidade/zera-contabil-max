"""Conferir com o Domínio: o saldo digitado (como o Domínio mostra) comparado com o saldo final do extrato."""

from datetime import date
from decimal import Decimal

import pytest

from app.servicos.conferencia_dominio import ler_saldo, linhas_conferencia
from app.servicos.extratos import importar_extrato
from tests.test_ofx import empresa, montar_ofx  # noqa: F401 — empresa com o plano de teste (BB 12345-6 = conta 8)

AGOSTO = date(2026, 8, 1)


@pytest.mark.parametrize(
    ("texto", "valor"),
    [("12.345,67", Decimal("12345.67")), ("12.345,67D", Decimal("12345.67")), ("1.000,00C", Decimal("-1000.00")),
     ("-1.000,00", Decimal("-1000.00")), ("R$ 50,5", Decimal("50.50")), ("", None), ("abc", False)],
)  # fmt: skip
def test_saldo_como_o_dominio_mostra(texto, valor):
    assert ler_saldo(texto) == valor


@pytest.fixture
def com_extrato(sessao, empresa):  # noqa: F811
    importar_extrato(sessao, empresa, "extrato.ofx", montar_ofx(), None)  # agosto, saldo final 600,00 em 31/08
    sessao.commit()
    return empresa


@pytest.mark.banco
def test_digitar_o_saldo_do_dominio_e_comparar(cliente, sessao, com_extrato):
    def conferir(saldo):
        conta = linhas_conferencia(sessao, com_extrato, AGOSTO)[0].conta
        dados = {"mes": "2026-08", f"saldo-{conta.id}-2026-08": saldo}
        return cliente.post(f"/empresas/{com_extrato.id}/conferencia-dominio", data=dados, follow_redirects=True).text

    tela = cliente.get(f"/empresas/{com_extrato.id}", params={"aba": "exportar", "mes": "2026-08"}).text
    assert "Conferir com o Domínio" in tela and "600,00" in tela and "falta digitar" in tela
    assert "as 1 conta(s) batem com o extrato" in conferir("600,00D")
    assert "✓ bate com o extrato" in cliente.get(f"/empresas/{com_extrato.id}?aba=exportar").text
    assert "o Domínio tem R$ 12,30 a mais que o extrato" in conferir("612,30")
    assert "o Domínio tem R$ 100,00 a menos que o extrato" in conferir("500,00D")
    assert "não é um valor" in conferir("seiscentos")
    conferir("")  # apagou: volta a faltar
    assert linhas_conferencia(sessao, com_extrato, AGOSTO)[0].situacao == "FALTA"


@pytest.mark.banco
def test_extrato_sem_saldo_do_fim_do_mes_nao_tem_o_que_comparar(sessao, empresa, monkeypatch):  # noqa: F811
    importar_extrato(sessao, empresa, "extrato.ofx", montar_ofx(fim="20260820"), None)  # vai só até 20/08
    sessao.commit()
    linha = linhas_conferencia(sessao, empresa, AGOSTO)[0]
    assert (linha.situacao, linha.sem_saldo) == ("SEM_EXTRATO", "o extrato vai só até 20/08")
