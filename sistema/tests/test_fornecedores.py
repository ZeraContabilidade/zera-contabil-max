"""Fornecedores a cadastrar no Domínio: a IA ou o usuário manda para a lista, a linha espera a conta, o plano
reimportado dá baixa sozinho, “Já cadastrei” e “Não é fornecedor”, e a lista em Excel."""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.modelos import Empresa, FornecedorACadastrar
from app.servicos.classificacao import classificar
from app.servicos.classificacao_ia import candidatas, classificar_com_ia, montar_contexto
from app.servicos.fornecedores import dar_baixa, lista, pela_ia
from tests.planos import PLANO, criar_plano
from tests.test_classificacao_ia import responder
from tests.test_revisao import (  # noqa: F401 — mesma empresa de teste (histórico, contas-chave e extrato de agosto)
    HTMX,
    empresa,
    recarregar,
    reduzidos,
    sugestao_de,
)

pytestmark = pytest.mark.banco
AGOSTO = (date(2026, 8, 1), date(2026, 8, 31))
NOVA_CONTA = (10576, "21301000195", "MERCEARIA ZETA LTDA", "A")


@pytest.fixture
def individual(empresa, sessao):  # noqa: F811
    """A empresa de teste com conta individual por fornecedor (grupo 2.1.3.01), como a Casa Criança."""
    empresa.usa_conta_individual, empresa.grupo_fornecedores = True, "2.1.3.01"
    sessao.commit()
    return empresa


def ia_com_fornecedor_novo(nome_conta: str, trecho: str = "MERCEARIA ZETA"):
    """IA falsa: as linhas com `trecho` são pagamento a fornecedor sem conta (conta_a_criar)."""
    base = responder({})

    def resposta(pedido):
        dados = base(pedido)
        for item, linha in zip(dados["itens"], pedido.pergunta.splitlines(), strict=True):
            item["conta_a_criar"] = nome_conta if trecho in linha else ""
        return dados

    return resposta


def test_ia_manda_fornecedor_novo_para_a_lista(individual, sessao, cliente, ia_falsa):
    ia_falsa.respostas = ia_com_fornecedor_novo("Mercearia Zeta Ltda")
    resultado = classificar_com_ia(sessao, individual, None, *AGOSTO)
    sessao.commit()
    assert "CONTA INDIVIDUAL POR FORNECEDOR: sim (grupo 2.1.3.01)" in ia_falsa.pedidos[-1][0].contexto
    assert resultado.fornecedores == 2 and "foram para “Fornecedores a cadastrar”" in resultado.resumo()

    [item] = lista(sessao, individual)
    f = item.fornecedor
    assert (f.nome, f.grupo, f.origem, item.linhas, item.valor) == (
        "MERCEARIA ZETA LTDA",
        "2.1.3.01",
        "IA",
        2,
        Decimal("97.00"),
    )
    zeta = sugestao_de(sessao, "MERCEARIA ZETA")
    assert reduzidos(zeta) == ("PENDENTE", "FORNECEDOR", None, 8) and zeta.fornecedor_id == f.id
    assert "cadastre “MERCEARIA ZETA LTDA” no grupo 2.1.3.01 no Domínio" in zeta.justificativa

    classificar(sessao, individual, *AGOSTO)  # “Classificar de novo” não mexe na linha que espera a conta
    assert recarregar(sessao, zeta).fornecedor_id == f.id
    assert zeta not in candidatas(sessao, individual, [zeta.movimento])  # nem a IA pergunta de novo

    tela = cliente.get(f"/empresas/{individual.id}", params={"aba": "revisao", "mes": "2026-08"}).text
    assert "Fornecedores a cadastrar no Domínio (1)" in tela and "cadastrar “MERCEARIA ZETA LTDA” no Domínio" in tela


def test_sem_conta_individual_a_ia_nao_cria_lista(empresa, sessao, ia_falsa):  # noqa: F811
    ia_falsa.respostas = ia_com_fornecedor_novo("MERCEARIA ZETA LTDA")
    classificar_com_ia(sessao, empresa, None, *AGOSTO)
    assert lista(sessao, empresa) == [] and sugestao_de(sessao, "MERCEARIA ZETA").fornecedor_id is None
    assert "CONTA INDIVIDUAL POR FORNECEDOR: não" in montar_contexto(sessao, empresa)


def test_fornecedor_que_ja_tem_conta_recebe_a_conta(individual, sessao, ia_falsa):
    ia_falsa.respostas = ia_com_fornecedor_novo("PAPELARIA CENTRAL", trecho="FULANO")  # a 10574 já existe
    classificar_com_ia(sessao, individual, None, *AGOSTO)
    assert reduzidos(sugestao_de(sessao, "FULANO DESCONHECIDO")) == ("APROVADO", "FORNECEDOR", 10574, 8)
    assert lista(sessao, individual) == []  # não entra na lista


def test_botao_fornecedor_novo_e_plano_reimportado_da_baixa(individual, sessao, cliente):
    zeta1, zeta2 = sugestao_de(sessao, "MERCEARIA ZETA"), sugestao_de(sessao, "MERCEARIA ZETA", vez=1)
    resposta = cliente.post(f"/empresas/{individual.id}/revisao/{zeta1.id}", data={"acao": "fornecedor"}, headers=HTMX)
    assert "cadastrar “MERCEARIA ZETA” no Domínio" in resposta.text
    assert recarregar(sessao, zeta2).fornecedor_id == zeta1.fornecedor_id  # a outra linha dele vai junto
    [item] = lista(sessao, individual)
    assert (item.fornecedor.origem, item.linhas) == ("USUARIO", 2)

    # o usuário criou a conta no Domínio e reimporta o plano (aqui: copiado de outra empresa com a conta nova)
    outra = Empresa(codigo_dominio=231, nome_curto="Modelo")
    sessao.add(outra)
    sessao.commit()
    criar_plano(sessao, outra, [*PLANO, NOVA_CONTA])
    tela = cliente.post(
        f"/empresas/{individual.id}/plano/copiar", data={"origem_id": str(outra.id)}, follow_redirects=True
    ).text
    assert "1 fornecedor(es) ganharam conta no plano" in tela and "MERCEARIA ZETA → 10576" in tela
    assert [reduzidos(recarregar(sessao, s)) for s in (zeta1, zeta2)] == [("APROVADO", "FORNECEDOR", 10576, 8)] * 2
    assert lista(sessao, individual) == []
    assert dar_baixa(sessao, individual) == []  # nada mais a dar baixa


def test_ja_cadastrei_e_nao_e_fornecedor(individual, sessao, cliente, ia_falsa):
    zeta = sugestao_de(sessao, "MERCEARIA ZETA")
    fulano = sugestao_de(sessao, "FULANO DESCONHECIDO")
    for linha in (zeta, fulano):
        cliente.post(f"/empresas/{individual.id}/revisao/{linha.id}", data={"acao": "fornecedor"})
    zeta, fulano = recarregar(sessao, zeta), recarregar(sessao, fulano)
    url = f"/empresas/{individual.id}/fornecedores"

    tela = cliente.post(f"{url}/{zeta.fornecedor_id}", data={"acao": "cadastrado", "conta": "10575", "mes": "2026-08"},
                        follow_redirects=True).text  # fmt: skip
    assert "MERCEARIA ZETA: conta 10575 – ZERA ASSESSORIA gravada em 2 linha(s)" in tela
    zeta = recarregar(sessao, zeta)
    assert reduzidos(zeta) == ("APROVADO", "USUARIO", 10575, 8) and zeta.conferido_por_id  # como na Revisão
    assert zeta.fornecedor.situacao == "CADASTRADO"

    tela = cliente.post(f"{url}/{fulano.fornecedor_id}", data={"acao": "descartar"}, follow_redirects=True).text
    assert "FULANO DESCONHECIDO saiu da lista. 1 linha(s) voltaram a pendentes" in tela
    descartado = sessao.scalar(select(FornecedorACadastrar).where(FornecedorACadastrar.situacao == "DESCARTADO"))
    fulano = recarregar(sessao, fulano)
    assert (fulano.status, fulano.origem, fulano.fornecedor_id) == ("PENDENTE", "PENDENTE", None)
    assert pela_ia(sessao, individual, fulano, descartado.nome, "", "") is None  # a IA não põe de volta

    tela = cliente.post(f"{url}/{descartado.id}", data={"acao": "descartar"}, follow_redirects=True).text
    assert "Este fornecedor não está mais na lista" in tela


def test_escolher_a_conta_tira_a_linha_da_espera(individual, sessao, cliente):
    zeta = sugestao_de(sessao, "MERCEARIA ZETA")
    cliente.post(f"/empresas/{individual.id}/revisao/{zeta.id}", data={"acao": "fornecedor"})
    cliente.post(f"/empresas/{individual.id}/revisao/{zeta.id}", data={"acao": "salvar", "conta": "359"})
    zeta = recarregar(sessao, zeta)
    assert reduzidos(zeta) == ("APROVADO", "USUARIO", 359, 8) and zeta.fornecedor_id is None
    assert lista(sessao, individual)[0].linhas == 1  # só a outra linha ainda espera


def test_lista_em_excel(individual, sessao, cliente):
    zeta = sugestao_de(sessao, "MERCEARIA ZETA")
    cliente.post(f"/empresas/{individual.id}/revisao/{zeta.id}", data={"acao": "fornecedor"})
    resposta = cliente.get(f"/empresas/{individual.id}/fornecedores-a-cadastrar.xlsx")
    assert resposta.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "fornecedores_a_cadastrar_230.xlsx" in resposta.headers["content-disposition"]
    folha = load_workbook(BytesIO(resposta.content)).active
    assert folha["A1"].value.startswith("Fornecedores a cadastrar no Domínio — Creche Teste")
    assert [c.value for c in folha[5]][:5] == ["MERCEARIA ZETA", None, "2.1.3.01", 2, 97]  # sem CNPJ no extrato


def test_botao_so_em_empresa_com_conta_individual(empresa, sessao, cliente):  # noqa: F811
    zeta = sugestao_de(sessao, "MERCEARIA ZETA")
    tela = cliente.get(f"/empresas/{empresa.id}", params={"aba": "revisao", "mes": "2026-08"}).text
    assert "Fornecedor novo" not in tela
    resposta = cliente.post(f"/empresas/{empresa.id}/revisao/{zeta.id}", data={"acao": "fornecedor"}, headers=HTMX)
    assert "não usa conta individual por fornecedor" in resposta.text
