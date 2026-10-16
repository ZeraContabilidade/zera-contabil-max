"""Extratos do BB no modelo que as creches baixam (15/10/2026): “Consultas - Extrato de conta corrente” (sem o nome
do banco, titular grudado no número) e a poupança com o cabeçalho inteiro numa linha e o valor alinhado à esquerda."""

from datetime import date
from decimal import Decimal

import pytest

from app.leitores import ler_extrato
from app.leitores.bb_conta_corrente import LeitorBBContaCorrente
from app.leitores.bb_poupanca import LeitorBBPoupanca
from tests.conftest import AMOSTRAS
from tests.test_extratos import PdfFalso, linha_de

TEXTO_CONSULTAS = "\n".join(
    [
        "G3380107210493451",
        "01/09/2026 07:29:12",
        "Consultas - Extrato de conta corrente",
        "Cliente - Conta atual",
        "Agência 1819-8",
        "Conta corrente 83431-9ASSOCIACAO EXEMPLO",
        "Período do extrato de 01 / 08 / 2026 até 31 / 08 / 2026",
        "Lançamentos",
        "Dt. balancete Dt. movimento Ag. origem Lote Histórico Documento Valor R$ Saldo",
        "Ouvidoria BB 0800 729 5678",
    ]
)


def test_conta_corrente_modelo_consultas_sem_o_nome_do_banco():
    leitor = LeitorBBContaCorrente()
    assert leitor.reconhece(PdfFalso(texto=TEXTO_CONSULTAS))
    assert not leitor.reconhece(PdfFalso(texto="Consultas - Extrato de conta corrente\nOutro banco"))
    lido = leitor.ler(PdfFalso(texto=TEXTO_CONSULTAS))
    assert (lido.agencia, lido.numero, lido.titular) == ("1819-8", "83431-9", "ASSOCIACAO EXEMPLO")
    assert (lido.inicio, lido.fim) == (date(2026, 8, 1), date(2026, 8, 31))
    assert len(lido.movimentos) == 3  # as páginas de exemplo do teste do BB


POUPANCA_DA_CRECHE = [
    *linha_de(165.0, ("Titularidade", 57), ("ASSOCIACAO", 119), ("EXEMPLO", 176)),
    *linha_de(
        179.0,
        ("Dt.", 57),
        ("lançamento", 70),
        ("Dt.", 116),
        ("base", 129),
        ("Dia", 161),
        ("Histórico", 180),
        ("Ag.", 320),
        ("origem", 335),
        ("Documento", 363),
        ("Informações", 409),
        ("Valor", 458),
        ("Saldo", 507),
    ),  # fmt: skip
    *linha_de(197.0, ("31/07/2026", 57), ("Saldo", 180), ("anterior", 204), ("1.000,00", 507, 548), ("C", 550)),
    *linha_de(
        210.0,
        ("04/08/2026", 57),
        ("03/08/2026", 116),
        ("248", 180),
        ("Resgate", 196),
        ("Automático", 229),
        ("1819-8", 320),
        ("9.181.903", 363),
        ("200,00", 458, 483),
        ("D", 486),
    ),  # fmt: skip
    *linha_de(
        222.0,
        ("12/08/2026", 57),
        ("11/08/2026", 116),
        ("11/8", 161),
        ("880", 180),
        ("Aplicacao", 196),
        ("Automatica", 240),
        ("1819-8", 320),
        ("9.181.911", 363),
        ("500,00", 458, 483),
        ("C", 486),
    ),  # fmt: skip
    # valor curto: o C/D fica grudado nele
    *linha_de(
        235.0,
        ("31/08/2026", 57),
        ("01/09/2026", 116),
        ("737", 180),
        ("Juros", 196),
        ("1819-8", 320),
        ("2,47", 458, 474),
        ("C", 477),
    ),  # fmt: skip
    *linha_de(260.0, ("Saldo", 57), ("total", 80), ("1.302,47", 400), ("C", 450)),
]
TEXTO_POUPANCA = "\n".join(
    [
        "Extratos - Poupança",
        "51 - POUPANÇA-OURO DIÁRIA",
        "Agência / Conta 1819-8 / 83431-9 Saldo: 1.300,00 C",
        "Período 01/08/2026 a 31/08/2026",
        "Titularidade ASSOCIACAO EXEMPLO",
    ]
)


def test_poupanca_modelo_das_creches():
    leitor = LeitorBBPoupanca()
    assert leitor.reconhece(PdfFalso(texto=TEXTO_POUPANCA))
    lido = leitor.ler(PdfFalso(texto=TEXTO_POUPANCA, paginas=[POUPANCA_DA_CRECHE]))
    assert [(m.sentido, m.valor, m.historico) for m in lido.movimentos] == [
        ("SAIDA", Decimal("200.00"), "Resgate Automático"),
        ("ENTRADA", Decimal("500.00"), "Aplicacao Automatica"),
        ("ENTRADA", Decimal("2.47"), "Juros"),
    ]
    # o saldo final é o “Saldo total” do fim (o do alto é de outra hora: antes dos juros)
    assert (lido.saldo_inicial, lido.saldo_final) == (Decimal("1000.00"), Decimal("1302.47"))
    assert not lido.avisos


@pytest.mark.amostras
@pytest.mark.parametrize("creche", ["carmem", "jandira", "pastor_mario", "rogerio"])
def test_extratos_reais_das_creches_fecham_com_o_saldo(creche):
    """PDFs reais de ago/2026 da associação 121 (conta corrente e poupança): lidos sem IA e o saldo confere."""
    pasta = AMOSTRAS / "DEMONSTRATIVOS 121 2026-08" / creche
    if not pasta.exists():
        pytest.skip("AMOSTRAS/ não está neste computador")
    for pdf in sorted(pasta.glob("extrato_*.pdf")):
        lido = ler_extrato(pdf.name, pdf.read_bytes())
        movimento = sum(m.valor if m.sentido == "ENTRADA" else -m.valor for m in lido.movimentos)
        assert lido.saldo_final - lido.saldo_inicial == movimento, pdf
        assert not lido.avisos, pdf
