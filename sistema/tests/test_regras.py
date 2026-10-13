"""Regras do escritório: “contém X → conta Y”, criadas na hora, valem antes do aprendizado e aprovam sozinhas."""

import pytest
from sqlalchemy import select

from app.modelos import MovimentoExtrato, Padrao
from tests.test_revisao import empresa, recarregar, sugestao_de  # noqa: F401 — empresa com o extrato de agosto

pytestmark = pytest.mark.banco


def tarifa(sessao):
    movimento = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.historico == "Tarifa Pacote de Serviços"))
    return recarregar(sessao, movimento.sugestao)


def criar(cliente, empresa, **dados):  # noqa: F811
    cliente.get(f"/empresas/{empresa.id}", params={"aba": "aprendizado", "mes": "2026-08"})  # agosto na tela
    return cliente.post(f"/empresas/{empresa.id}/regras", data=dados, follow_redirects=True).text


def test_regra_aprova_as_linhas_que_combinam(cliente, empresa, sessao):  # noqa: F811
    tela = criar(cliente, empresa, texto="mercearia zeta", sentido="SAIDA", conta="359", natureza="Lanche; café")
    assert "Regra criada: “MERCEARIA ZETA” → 359" in tela and "2 linha(s) de agosto/2026 combinam" in tela
    assert "Regras do escritório" in tela and "só pagamentos (saídas)" in tela
    for vez in (0, 1):
        linha = recarregar(sessao, sugestao_de(sessao, "MERCEARIA ZETA", vez=vez))
        assert (linha.status, linha.origem, linha.confianca, linha.conta_debito.reduzido) == (
            "APROVADO", "ESCRITORIO", 97, 359,
        )  # fmt: skip
        assert "LANCHE, CAFE" in linha.complemento.upper().replace("É", "E")


def test_regra_vale_antes_da_regra_do_banco_e_respeita_o_sentido(cliente, empresa, sessao):  # noqa: F811
    criar(cliente, empresa, texto="TARIFA", sentido="ENTRADA", conta="359")  # só entradas: a tarifa (saída) fica
    assert tarifa(sessao).origem != "ESCRITORIO"
    criar(cliente, empresa, texto="TARIFA", sentido="", conta="359")  # a mesma regra, agora para as duas
    linha = tarifa(sessao)
    assert (linha.origem, linha.conta_debito.reduzido) == ("ESCRITORIO", 359)  # e não a conta-chave 535


def test_conferido_a_mao_nao_muda_e_apagar_desfaz(cliente, empresa, sessao):  # noqa: F811
    fulano = sugestao_de(sessao, "FULANO DESCONHECIDO")
    cliente.post(f"/empresas/{empresa.id}/revisao/{fulano.id}", data={"acao": "salvar", "conta": "355"})
    criar(cliente, empresa, texto="FULANO", conta="359")
    assert recarregar(sessao, fulano).conta_debito.reduzido == 355  # a escolha à mão vale
    zeta = sugestao_de(sessao, "MERCEARIA ZETA")
    criar(cliente, empresa, texto="ZETA", conta="359")
    assert recarregar(sessao, zeta).origem == "ESCRITORIO"
    regra_id = sessao.scalar(select(Padrao.id).where(Padrao.tipo == "REGRA", Padrao.chave == "ZETA"))
    tela = cliente.post(f"/empresas/{empresa.id}/regras/{regra_id}/apagar", follow_redirects=True).text
    assert "Regra “ZETA” apagada" in tela
    assert recarregar(sessao, zeta).origem != "ESCRITORIO"


def test_regra_com_problema_explica(cliente, empresa):  # noqa: F811
    assert "pelo menos 3 letras" in criar(cliente, empresa, texto="ab", conta="359")
    assert "conta" in criar(cliente, empresa, texto="TARIFA", conta="999999").lower()
