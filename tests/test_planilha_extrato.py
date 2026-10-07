"""Extrato em Excel/CSV: valores e datas do jeito brasileiro, títulos comuns, IA para o layout desconhecido,
confirmação na 1ª vez de cada modelo e conta bancária lembrada (planilhas fictícias montadas no teste)."""

import io
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.leitores.planilha import (
    PAPEIS,
    achar_titulos,
    ler_linhas,
    montar,
    parece_planilha,
    valor_data,
    valor_dinheiro,
)
from app.modelos import ContaBancaria, Empresa, Extrato, ModeloPlanilha
from tests.conftest import entrar
from tests.planos import criar_plano


def xlsx(linhas) -> bytes:
    livro = Workbook()
    for linha in linhas:
        livro.active.append(linha)
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


def itau(mes=8, saldo_anterior=1000.0) -> bytes:
    """Extrato fictício com títulos e com banco, agência e conta no alto."""
    return xlsx(
        [
            ["Extrato de conta corrente"],
            ["Banco Itaú", "Agência: 1234", "Conta: 5555-1"],
            [],
            ["Data", "Lançamento", "Documento", "Valor (R$)", "Saldo (R$)"],
            [datetime(2026, mes - 1, 30), "SALDO ANTERIOR", None, None, saldo_anterior],
            [datetime(2026, mes, 5), "PIX RECEBIDO PREFEITURA", None, 500.0, saldo_anterior + 500],
            [datetime(2026, mes, 10), "SISPAG FORNECEDORES", "123", -200.0, saldo_anterior + 300],
            [datetime(2026, mes, 28), "SALDO DO DIA", None, None, saldo_anterior + 300],
        ]
    )


def csv_debito_credito(mes=8) -> bytes:
    """CSV sem banco nem conta, com Débito e Crédito separados (Windows-1252)."""
    return (
        "Data;Histórico;Débito;Crédito;Saldo\r\n"
        f"05/{mes:02d}/2026;TARIFA PACOTE DE SERVIÇOS;12,50;;987,50\r\n"
        f"10/{mes:02d}/2026;DEPÓSITO;;100,00;1.087,50\r\n"
    ).encode("cp1252")


SEM_TITULOS = xlsx([[datetime(2026, 8, 5), "PIX ENVIADO MERCADO", -50.0], [datetime(2026, 8, 9), "DEPOSITO", 80.0]])


# ---------------------------------------------------------------- leitura (sem banco)


@pytest.mark.parametrize(
    ("celula", "esperado"),
    [
        (1234.5, Decimal("1234.50")),
        ("1.234,56", Decimal("1234.56")),
        ("-1.234,56", Decimal("-1234.56")),
        ("1.234,56 D", Decimal("-1234.56")),
        ("(10,00)", Decimal("-10.00")),
        ("R$ 99,90", Decimal("99.90")),
        ("1234.56", Decimal("1234.56")),
        ("", None),
        ("abc", None),
    ],
)
def test_valores_do_jeito_dos_bancos(celula, esperado):
    assert valor_dinheiro(celula) == esperado


def test_datas():
    assert valor_data(datetime(2026, 8, 5, 10, 30)) == date(2026, 8, 5)
    assert valor_data("05/08/2026") == valor_data("05/08/26") == valor_data("2026-08-05") == date(2026, 8, 5)
    assert valor_data("SALDO") is None


def test_parece_planilha_pelo_conteudo():
    assert parece_planilha("x.xlsx", itau()) and parece_planilha("x.csv", csv_debito_credito())
    assert not parece_planilha("x.ofx", b"OFXHEADER:100\n<OFX>\n<STMTRS>\n")
    assert not parece_planilha("x.pdf", b"%PDF-1.4 ...")


def test_titulos_e_saldo_pela_planilha():
    linhas = ler_linhas(itau())
    indice, colunas = achar_titulos(linhas)
    assert indice == 3 and (colunas["data"], colunas["historico"], colunas["valor"], colunas["saldo"]) == (0, 1, 3, 4)
    montagem = montar(linhas, indice, colunas)
    assert (montagem.saldo_inicial, montagem.saldo_final) == (Decimal("1000.00"), Decimal("1300.00"))
    assert [(m.historico, m.valor, m.sentido, m.documento) for m in montagem.movimentos] == [
        ("PIX RECEBIDO PREFEITURA", Decimal("500.00"), "ENTRADA", ""),
        ("SISPAG FORNECEDORES", Decimal("200.00"), "SAIDA", "123"),
    ]


def test_debito_e_credito_separados_e_saldo_inicial_pela_primeira_linha():
    linhas = ler_linhas(csv_debito_credito())
    indice, colunas = achar_titulos(linhas)
    montagem = montar(linhas, indice, colunas)
    assert [(m.historico, m.valor, m.sentido) for m in montagem.movimentos] == [
        ("TARIFA PACOTE DE SERVIÇOS", Decimal("12.50"), "SAIDA"),
        ("DEPÓSITO", Decimal("100.00"), "ENTRADA"),
    ]
    assert (montagem.saldo_inicial, montagem.saldo_final) == (Decimal("1000.00"), Decimal("1087.50"))


# ---------------------------------------------------------------- tela (com banco)


@pytest.fixture
def empresa(sessao, criar_usuario, cliente):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    return nova


def enviar(cliente, empresa, *arquivos):
    return cliente.post(
        f"/empresas/{empresa.id}/extratos",
        files=[("arquivos", (nome, conteudo)) for nome, conteudo in arquivos],
        follow_redirects=True,
    )


def confirmar(cliente, empresa, sessao, colunas, conta, linha_titulos):
    from app.modelos import ArquivoOriginal

    arquivo = sessao.scalar(select(ArquivoOriginal).order_by(ArquivoOriginal.id.desc()))
    formulario = {"linha_titulos": str(linha_titulos), "conta": "nova", **{f"col_{p}": "-1" for p in PAPEIS}}
    formulario |= {f"col_{papel}": str(coluna) for papel, coluna in colunas.items()}
    formulario |= conta
    return cliente.post(
        f"/empresas/{empresa.id}/extratos/planilha/{arquivo.id}", data=formulario, follow_redirects=True
    )


@pytest.mark.banco
def test_primeira_vez_confirma_depois_vai_direto(cliente, empresa, sessao):
    tela = enviar(cliente, empresa, ("itau-agosto.xlsx", itau())).text
    assert "Confirmar planilha de extrato" in tela and "colunas sugeridas pelos títulos" in tela
    assert "PIX RECEBIDO PREFEITURA" in tela  # as primeiras linhas aparecem para conferir
    assert 'value="5555-1"' in tela and 'value="341" selected' in tela  # banco e conta escritos na planilha
    assert sessao.scalar(select(func.count()).select_from(Extrato)) == 0

    conta_nova = {"nova_banco": "341", "nova_agencia": "1234", "nova_numero": "5555-1", "nova_tipo": "BANCO"}
    colunas = {"data": 0, "historico": 1, "documento": 2, "valor": 3, "saldo": 4}
    tela = confirmar(cliente, empresa, sessao, colunas, conta_nova, linha_titulos=3).text
    assert "itau-agosto.xlsx: Itaú · ag. 1234 · conta corrente 5555-1, 2 movimento(s) novo(s) — saldo confere" in tela
    assert "9 – BANCO ITAU CC 5555-1" in tela
    modelo = sessao.scalar(select(ModeloPlanilha))
    assert modelo.confirmado and modelo.origem == "TITULOS"

    # setembro, mesmo modelo: entra direto (banco e conta escritos no alto da planilha)
    tela = enviar(cliente, empresa, ("itau-setembro.xlsx", itau(mes=9, saldo_anterior=1300.0))).text
    assert "itau-setembro.xlsx: Itaú · ag. 1234 · conta corrente 5555-1, 2 movimento(s) novo(s)" in tela
    assert sessao.scalar(select(func.count()).select_from(ContaBancaria)) == 1


@pytest.mark.banco
def test_csv_sem_conta_lembra_a_conta_escolhida(cliente, empresa, sessao):
    enviar(cliente, empresa, ("extrato.csv", csv_debito_credito()))
    conta_bb = {"nova_banco": "001", "nova_agencia": "1234-5", "nova_numero": "12345-6", "nova_tipo": "BANCO"}
    colunas = {"data": 0, "historico": 1, "debito": 2, "credito": 3, "saldo": 4}
    assert "saldo confere" in confirmar(cliente, empresa, sessao, colunas, conta_bb, linha_titulos=0).text
    assert sessao.scalar(select(ContaBancaria)).assinatura_planilha  # a conta guardou o modelo da planilha

    tela = enviar(cliente, empresa, ("setembro.csv", csv_debito_credito(mes=9))).text
    assert "setembro.csv: Banco do Brasil · ag. 1234-5 · conta corrente 12345-6, 2 movimento(s) novo(s)" in tela


@pytest.mark.banco
def test_layout_desconhecido_a_ia_sugere_e_o_usuario_confirma(cliente, empresa, sessao, ia_falsa):
    ia_falsa.respostas["colunas_planilha"] = {
        "linha_titulos": -1, "data": 0, "historico": 1, "complemento": -1, "documento": -1, "valor": 2,
        "debito": -1, "credito": -1, "sentido": -1, "saldo": -1,
    }  # fmt: skip
    tela = enviar(cliente, empresa, ("banco-x.xlsx", SEM_TITULOS)).text
    assert "colunas sugeridas pela IA" in tela
    assert len([p for p, _ in ia_falsa.pedidos if p.finalidade == "colunas_planilha"]) == 1
    tela = cliente.get(f"/empresas/{empresa.id}?aba=extratos").text
    assert "Planilhas esperando a sua confirmação" in tela and "banco-x.xlsx" in tela

    conta = {"nova_banco": "001", "nova_agencia": "", "nova_numero": "777-1", "nova_tipo": "BANCO"}
    sem_data = confirmar(cliente, empresa, sessao, {"historico": 1, "valor": 2}, conta, linha_titulos=-1)
    assert sem_data.status_code == 400 and "Escolha a coluna da data" in sem_data.text
    tela = confirmar(cliente, empresa, sessao, {"data": 0, "historico": 1, "valor": 2}, conta, linha_titulos=-1).text
    assert "2 movimento(s) novo(s) — sem saldo para conferir" in tela
    assert "Planilhas esperando" not in tela
    assert len([p for p, _ in ia_falsa.pedidos if p.finalidade == "colunas_planilha"]) == 1  # não perguntou de novo
