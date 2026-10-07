"""OFX de qualquer banco: SGML (OFX 1.x, Windows-1252, vírgula decimal) e XML (OFX 2.x), a mesma conta
escrita de jeitos diferentes, PDF e OFX do mesmo mês sem duplicar e o saldo inicial pelo mês anterior."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.leitores import ler_extrato
from app.modelos import ContaBancaria, Empresa, MovimentoExtrato
from app.servicos.extratos import importar_extrato, mesma_conta
from app.servicos.plano import ErroLeitura
from tests.conftest import entrar
from tests.planos import criar_plano
from tests.test_extratos import AGOSTO, extrato_lido, mov

CABECALHO_SGML = (
    "OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:102\r\nSECURITY:NONE\r\nENCODING:USASCII\r\nCHARSET:1252\r\n"
    "COMPRESSION:NONE\r\nOLDFILEUID:NONE\r\nNEWFILEUID:NONE\r\n\r\n"
)
AGOSTO_OFX = [  # os mesmos movimentos de AGOSTO (test_extratos), com o texto do jeito do OFX
    ("20260805", "-100.00", "Pagamento de Boleto FORNECEDOR EXEMPLO", "80501"),
    ("20260805", "-100,00", "Pagto conta água", "80502"),  # vírgula decimal, acento em Windows-1252
    ("20260811", "800.00", "Transferência recebida PREFEITURA", "80503"),
]


def montar_ofx(movimentos=AGOSTO_OFX, acctid="12345-6", agencia="1234-5", banco="001", saldo="600.00",
               inicio="20260801", fim="20260831", extra="") -> bytes:  # fmt: skip
    corpo = (
        "<OFX>\r\n<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        "<DTSERVER>20260901120000[-3:BRT]<LANGUAGE>POR</SONRS></SIGNONMSGSRSV1>\r\n"
        "<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS><CURDEF>BRL\r\n"
        f"<BANKACCTFROM><BANKID>{banco}<BRANCHID>{agencia}<ACCTID>{acctid}<ACCTTYPE>CHECKING</BANKACCTFROM>\r\n"
        f"<BANKTRANLIST><DTSTART>{inicio}<DTEND>{fim}\r\n"
    )
    for dia, valor, memo, documento in movimentos:
        tipo = "DEBIT" if valor.startswith("-") else "CREDIT"
        corpo += (
            f"<STMTTRN>\r\n<TRNTYPE>{tipo}\r\n<DTPOSTED>{dia}120000[-3:BRT]\r\n<TRNAMT>{valor}\r\n"
            f"<FITID>{dia}{documento}\r\n<CHECKNUM>{documento}\r\n<MEMO>{memo}\r\n</STMTTRN>\r\n"
        )
    corpo += f"</BANKTRANLIST>\r\n<LEDGERBAL><BALAMT>{saldo}<DTASOF>{fim}</LEDGERBAL>\r\n</STMTRS>{extra}"
    corpo += "</STMTTRNRS></BANKMSGSRSV1></OFX>\r\n"
    return (CABECALHO_SGML + corpo).encode("cp1252")


OFX_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<?OFX OFXHEADER="200" VERSION="211" SECURITY="NONE"?>\n'
    "<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>BRL</CURDEF><BANKACCTFROM><BANKID>0341</BANKID>"
    "<ACCTID>05555-1</ACCTID><ACCTTYPE>SAVINGS</ACCTTYPE></BANKACCTFROM><BANKTRANLIST>"
    "<DTSTART>20260801</DTSTART><DTEND>20260831</DTEND><STMTTRN><TRNTYPE>CREDIT</TRNTYPE>"
    "<DTPOSTED>20260810</DTPOSTED><TRNAMT>12.34</TRNAMT><FITID>a1</FITID><NAME>JUROS POUPANÇA</NAME></STMTTRN>"
    "</BANKTRANLIST><LEDGERBAL><BALAMT>1012.34</BALAMT><DTASOF>20260831</DTASOF></LEDGERBAL></STMTRS>"
    "</STMTTRNRS></BANKMSGSRSV1></OFX>"
).encode()

CARTAO = b"<OFX><CREDITCARDMSGSRSV1><CCSTMTRS><CURDEF>BRL</CCSTMTRS></CREDITCARDMSGSRSV1></OFX>"


# ---------------------------------------------------------------- leitura (sem banco)


def test_ofx_sgml_do_bb():
    lido = ler_extrato("extrato.ofx", montar_ofx())
    assert (lido.leitor, lido.banco, lido.agencia, lido.numero, lido.tipo) == (
        "OFX",
        "001",
        "1234-5",
        "12345-6",
        "BANCO",
    )
    assert (lido.inicio, lido.fim, lido.saldo_final, lido.saldo_inicial) == (
        date(2026, 8, 1),
        date(2026, 8, 31),
        Decimal("600.00"),
        None,  # o OFX não traz saldo inicial
    )
    assert [(m.data.day, m.sentido, m.valor, m.historico, m.documento) for m in lido.movimentos] == [
        (5, "SAIDA", Decimal("100.00"), "Pagamento de Boleto FORNECEDOR EXEMPLO", "80501"),
        (5, "SAIDA", Decimal("100.00"), "Pagto conta água", "80502"),
        (11, "ENTRADA", Decimal("800.00"), "Transferência recebida PREFEITURA", "80503"),
    ]


def test_ofx_xml_de_outro_banco_sem_agencia():
    lido = ler_extrato("itau.ofx", OFX_XML)
    assert (lido.banco, lido.agencia, lido.numero, lido.tipo) == ("341", "", "05555-1", "POUPANCA")
    assert [(m.historico, m.valor, m.sentido) for m in lido.movimentos] == [
        ("JUROS POUPANÇA", Decimal("12.34"), "ENTRADA")
    ]


@pytest.mark.parametrize(
    ("conteudo", "trecho"),
    [
        (CABECALHO_SGML.encode() + CARTAO, "cartão de crédito"),
        (montar_ofx(extra="<STMTRS><BANKACCTFROM><ACCTID>999</BANKACCTFROM></STMTRS>"), "2 contas juntas"),
        (montar_ofx(acctid=""), "número da conta"),
    ],
)  # fmt: skip
def test_ofx_com_problema(conteudo, trecho):
    with pytest.raises(ErroLeitura, match=trecho):
        ler_extrato("x.ofx", conteudo)


def test_mesma_conta_escrita_de_jeitos_diferentes():
    pdf = ContaBancaria(agencia="2180-6", numero="72637-0")
    assert mesma_conta(pdf, "", "0000726370")  # OFX sem agência e com zeros
    assert mesma_conta(pdf, "2180", "72637-0")
    assert not mesma_conta(pdf, "9999", "72637-0")  # outra agência
    assert not mesma_conta(pdf, "2180-6", "72637-1")


# ---------------------------------------------------------------- importação (com banco)


@pytest.fixture
def empresa(sessao, criar_usuario, cliente):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    return nova


@pytest.mark.banco
def test_enviar_ofx_pela_tela(cliente, empresa, sessao):
    arquivos = [("arquivos", ("extrato.ofx", montar_ofx()))]
    tela = cliente.post(f"/empresas/{empresa.id}/extratos", files=arquivos, follow_redirects=True).text
    assert "3 movimento(s) novo(s)" in tela and "sem saldo para conferir" in tela
    assert "não traz o saldo inicial" in tela
    assert "8 – BCO BRASIL CC 12345-6" in tela


@pytest.mark.banco
def test_pdf_e_ofx_do_mesmo_mes_nao_duplicam(empresa, sessao, monkeypatch):
    combinado = {"agosto.pdf": extrato_lido(AGOSTO, final="600")}
    monkeypatch.setattr(
        "app.servicos.extratos.ler_extrato", lambda nome, conteudo: combinado.get(nome) or ler_extrato(nome, conteudo)
    )
    importar_extrato(sessao, empresa, "agosto.pdf", b"%PDF-falso", None)
    ofx = importar_extrato(sessao, empresa, "agosto.ofx", montar_ofx(acctid="0000123456", agencia=""), None)
    sessao.commit()
    assert (ofx.importacao.resumo["novos"], ofx.importacao.resumo["repetidos"]) == (0, 3)
    assert sessao.scalar(select(func.count()).select_from(ContaBancaria)) == 1  # a mesma conta
    assert sessao.scalar(select(func.count()).select_from(MovimentoExtrato)) == 3
    assert ofx.conferencia == "SEM_SALDO"  # não há extrato de julho para dar o saldo inicial


@pytest.mark.banco
def test_saldo_inicial_do_ofx_vem_do_extrato_anterior(empresa, sessao, monkeypatch):
    julho = extrato_lido([mov(10, "50.00", "ENTRADA", "Depósito", "")], inicial="950", final="1000")
    julho.inicio, julho.fim = date(2026, 7, 1), date(2026, 7, 31)
    julho.movimentos[0].data = date(2026, 7, 10)
    monkeypatch.setattr(
        "app.servicos.extratos.ler_extrato",
        lambda nome, conteudo: julho if nome == "julho.pdf" else ler_extrato(nome, conteudo),
    )
    importar_extrato(sessao, empresa, "julho.pdf", b"%PDF-falso", None)
    agosto = importar_extrato(sessao, empresa, "agosto.ofx", montar_ofx(saldo="1600.00"), None)
    assert (agosto.saldo_inicial, agosto.saldo_final, agosto.conferencia) == (
        Decimal("1000.00"),
        Decimal("1600.00"),
        "CONFERE",
    )  # 1.000 + 800 − 200 = 1.600
    errado = importar_extrato(sessao, empresa, "setembro.ofx", montar_ofx(
        [("20260902", "-10.00", "Tarifa", "1")], saldo="1500.00", inicio="20260901", fim="20260930"), None)  # fmt: skip
    assert (errado.conferencia, errado.diferenca) == ("DIFERENCA", Decimal("-90.00"))  # 1.600 − 10 ≠ 1.500
