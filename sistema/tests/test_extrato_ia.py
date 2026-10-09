"""Leitor universal com IA: PDF de banco sem leitor próprio. A IA lê página por página; o extrato só entra
se o saldo conferir. Sem custo: usa a IA falsa e páginas de texto montadas no teste."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.leitores import NaoReconhecido
from app.leitores.universal_ia import juntar_paginas
from app.modelos import Empresa, Extrato
from app.servicos.extratos import importar_extrato
from app.servicos.plano import ErroLeitura
from tests.conftest import entrar
from tests.planos import criar_plano

CABECALHO = {"banco": "", "agencia": "", "conta": "", "tipo": "BANCO", "titular": "", "inicio": "", "fim": ""}
PAGINA_1 = {
    **CABECALHO,
    "e_extrato": True,
    "banco": "Itaú Unibanco",
    "agencia": "1234",
    "conta": "5555-1",  # no plano de teste: 9 – BANCO ITAU CC 5555-1
    "titular": "ASSOCIACAO EXEMPLO",
    "inicio": "2026-08-01",
    "fim": "2026-08-31",
    "saldo_inicial": "1000.00",
    "saldo_final": "",
    "movimentos": [
        {"data": "2026-08-05", "historico": "PIX RECEBIDO", "complemento": "PREFEITURA EXEMPLO",
         "documento": "", "valor": "500.00", "sentido": "ENTRADA"},
        {"data": "2026-13-40", "historico": "LINHA ESTRANHA", "complemento": "", "documento": "",
         "valor": "1.00", "sentido": "SAIDA"},  # data impossível: fica de fora
    ],
}  # fmt: skip
PAGINA_2 = {
    **CABECALHO,
    "e_extrato": True,
    "saldo_inicial": "",
    "saldo_final": "1300.00",
    "movimentos": [
        {"data": "2026-08-10", "historico": "SISPAG FORNECEDORES", "complemento": "MERCADO EXEMPLO",
         "documento": "123", "valor": "200.00", "sentido": "SAIDA"},
    ],
}  # fmt: skip


def test_juntar_as_paginas_lidas_pela_ia():
    lido = juntar_paginas([PAGINA_1, {"e_extrato": False}, PAGINA_2])
    assert (lido.banco, lido.agencia, lido.numero, lido.titular) == (
        "Itaú Unibanco",
        "1234",
        "5555-1",
        "ASSOCIACAO EXEMPLO",
    )
    assert (lido.saldo_inicial, lido.saldo_final, lido.exige_conferencia) == (
        Decimal("1000.00"),
        Decimal("1300.00"),
        True,
    )
    assert [(m.historico, m.valor, m.sentido) for m in lido.movimentos] == [
        ("PIX RECEBIDO", Decimal("500.00"), "ENTRADA"),
        ("SISPAG FORNECEDORES", Decimal("200.00"), "SAIDA"),
    ]
    assert "1 linha(s) lidas pela IA ficaram de fora" in lido.avisos[0].texto
    with pytest.raises(ErroLeitura, match="não parece um extrato"):
        juntar_paginas([{"e_extrato": False}])


@pytest.fixture
def empresa(sessao, criar_usuario, cliente):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    return nova


@pytest.fixture
def pdf_de_outro_banco(monkeypatch):
    """Nenhum leitor próprio reconhece o PDF; as páginas de texto são as do teste."""

    def nao_reconhece(nome, conteudo):
        raise NaoReconhecido(f"Não reconheci o extrato “{nome}”.")

    monkeypatch.setattr("app.servicos.extratos.ler_extrato", nao_reconhece)
    monkeypatch.setattr("app.leitores.universal_ia.paginas_do_pdf", lambda conteudo: ["página 1", "página 2"])


def responder(pagina_2=PAGINA_2):
    def resposta(pedido):
        return PAGINA_1 if "Página 1 de 2" in pedido.pergunta else pagina_2

    return resposta


@pytest.mark.banco
def test_pdf_de_outro_banco_lido_pela_ia(empresa, sessao, ia_falsa, pdf_de_outro_banco):
    ia_falsa.respostas = responder()
    extrato = importar_extrato(sessao, empresa, "itau.pdf", b"%PDF-falso", None)
    assert (extrato.leitor, extrato.conferencia) == ("Leitura pela IA (PDF)", "CONFERE")
    assert extrato.conta_bancaria.rotulo == "Itaú · ag. 1234 · conta corrente 5555-1"
    assert extrato.conta_bancaria.conta_chave.conta.reduzido == 9
    assert any("lido pela IA" in aviso["texto"] for aviso in extrato.importacao.avisos)
    assert len(ia_falsa.pedidos) == 2  # uma chamada por página
    assert all(pedido.forte and pedido.finalidade == "leitura_pdf" for pedido, _ in ia_falsa.pedidos)


@pytest.mark.banco
def test_saldo_que_nao_bate_na_leitura_pela_ia_recusa_o_arquivo(cliente, empresa, sessao, ia_falsa, pdf_de_outro_banco):
    ia_falsa.respostas = responder({**PAGINA_2, "saldo_final": "9999.00"})
    tela = cliente.post(
        f"/empresas/{empresa.id}/extratos", files=[("arquivos", ("itau.pdf", b"%PDF-falso"))], follow_redirects=True
    ).text
    assert "A IA leu o extrato “itau.pdf”, mas o saldo não bate" in tela
    assert "mande o OFX ou o Excel do banco" in tela
    assert sessao.scalar(select(func.count()).select_from(Extrato)) == 0  # nada foi gravado


@pytest.mark.banco
def test_sem_ia_o_pdf_de_outro_banco_pede_o_ofx(empresa, sessao, pdf_de_outro_banco):
    with pytest.raises(ErroLeitura, match="leitura com IA não está disponível"):
        importar_extrato(sessao, empresa, "itau.pdf", b"%PDF-falso", None)


@pytest.mark.banco
def test_arquivo_que_nao_e_pdf_nem_conhecido_nao_vai_para_a_ia(empresa, sessao, ia_falsa):
    with pytest.raises(ErroLeitura, match="Não reconheci o extrato"):
        importar_extrato(sessao, empresa, "notas.txt", b"qualquer coisa", None)
    assert ia_falsa.pedidos == []
