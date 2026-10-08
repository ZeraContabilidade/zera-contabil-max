"""lanctos.txt do Domínio: igual byte a byte ao arquivo que o Domínio já aceita (arquivo de ouro) e conferência
linha a linha — os 3 erros do modelo do escritório e os outros que bloqueiam a exportação (§3.6, §11.1)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modelos import ContaContabil
from app.servicos.exportacao import LinhaLancto, conferir_txt, formatar_valor, gerar_txt, ler_txt, texto_windows
from tests.conftest import AMOSTRAS, DADOS


def sem_as_linhas(conteudo: bytes, numeros: set[int]) -> bytes:
    linhas = conteudo.split(b"\r\n")
    return b"".join(linha + b"\r\n" for numero, linha in enumerate(linhas, 1) if linha and numero not in numeros)


def test_arquivo_de_ouro():
    """O lanctos.txt de exemplo (cópia anonimizada do aceito pelo Domínio, com 2 dos erros do modelo): a conferência
    acha os erros e, sem eles, o arquivo lido e gerado de novo sai idêntico, byte a byte."""
    exemplo = (DADOS / "lanctos_exemplo.txt").read_bytes()
    problemas = conferir_txt(exemplo, codigo_empresa=230)
    assert [p.linha for p in problemas] == [11, 12]  # conta “10595.” e data “28/01//2026”
    ouro = sem_as_linhas(exemplo, {11, 12})
    assert gerar_txt(ler_txt(ouro), 230) == ouro
    assert conferir_txt(ouro, codigo_empresa=230) == []


@pytest.mark.parametrize(
    ("valor", "texto"),
    [("150.17", "150,17"), ("346.50", "346,5"), ("120.00", "120"), ("2280.60", "2280,6"), ("80000", "80000"),
     ("0.05", "0,05"), ("1234567.89", "1234567,89"), ("12.5", "12,5")],
)  # fmt: skip
def test_valor_como_a_macro_gravava(valor, texto):
    assert formatar_valor(Decimal(valor)) == texto


def test_texto_so_com_o_que_o_windows_grava():
    assert texto_windows("CONTRIBUIÇÃO NEGOCIAL – SÃO PAULO") == "CONTRIBUIÇÃO NEGOCIAL – SÃO PAULO"
    assert texto_windows("ŐRSÉG 😀 LTDA") == "ORSÉG  LTDA"  # letra fora do Windows-1252 perde o acento ou some
    assert texto_windows("LINHA 1\nLINHA 2\tFIM") == "LINHA 1 LINHA 2 FIM"


def test_conta_em_branco_e_aceita():
    """Conta que não existe no plano (a poupança da Casa Criança) vai em branco: o Domínio aceita (08/10/2026)."""
    linha = LinhaLancto(date(2026, 8, 11), 31, None, Decimal("22.66"), "BANCO DO BRASIL - IR S/ APLICACAO - S/N")
    conteudo = gerar_txt([linha], 230)
    assert conteudo == b"11/08/2026;31;;22,66;;BANCO DO BRASIL - IR S/ APLICACAO - S/N;1;230;;\r\n"
    assert conferir_txt(conteudo, codigo_empresa=230) == []


def _arquivo(*linhas: str) -> bytes:
    return "".join(f"{linha}\r\n" for linha in linhas).encode("cp1252")


def test_os_3_erros_do_modelo_do_escritorio():
    conteudo = _arquivo(
        "05/01/2026;492;8;150,17;;TRANSPORTES EXEMPLO - VALE TRANSPORTE - 841;1;230;;",
        "19/01/2026;10595.;8;247,5;;SINDICATO EXEMPLO - CONTRIBUIÇÃO NEGOCIAL - S/N;1;230;;",
        "28/01//2026;560;8;892,49;;FULANA DE TAL - RESCISÃO - S/N;1;230;;",
        "28/01//2027;521;8;2070;;FULANA DE TAL - MARMITA - 22;1;230;;",
    )
    assert [p.texto for p in conferir_txt(conteudo, codigo_empresa=230)] == [
        "Linha 2: conta débito “10595.” inválida (só o código reduzido, ex.: 355).",
        "Linha 3: data “28/01//2026” inválida (use dd/mm/aaaa).",
        "Linha 4: data “28/01//2027” inválida (use dd/mm/aaaa).",
    ]


def test_outros_erros_que_bloqueiam():
    contas = {
        8: ContaContabil(reduzido=8, descricao="BCO BRASIL CC", tipo="A", ativa=True),
        355: ContaContabil(reduzido=355, descricao="ÁGUA E ESGOTO", tipo="A", ativa=True),
        353: ContaContabil(reduzido=353, descricao="DESPESAS GERAIS", tipo="S", ativa=True),
        999: ContaContabil(reduzido=999, descricao="CONTA ANTIGA", tipo="A", ativa=False),
    }
    conteudo = _arquivo(
        "03/08/2026;355;8;600,35;;SABESP - CONTA DE AGUA - S/N;1;230;;",  # certa
        "03/08/2026;8;8;10;;MESMA CONTA;1;230;;",
        "03/08/2026;355;8;0;;VALOR ZERO;1;230;;",
        "03/08/2026;355;8;1.234,56;;VALOR COM MILHAR;1;230;;",
        "03/08/2026;355;8;10;;COM ; NO COMPLEMENTO;1;230;;",
        "03/09/2026;355;8;10;;FORA DO MÊS;1;230;;",
        "03/08/2026;353;8;10;;GRUPO;1;230;;",
        "03/08/2026;999;8;10;;SAIU DO PLANO;1;230;;",
        "03/08/2026;;;10;;SEM CONTA NENHUMA;1;230;;",
        "03/08/2026;355;8;10;;OUTRA EMPRESA;1;231;;",
        "31/02/2026;355;8;10;;DIA QUE NÃO EXISTE;1;230;;",
    )
    problemas = conferir_txt(conteudo, contas, date(2026, 8, 1), date(2026, 8, 31), 230)
    assert [p.texto for p in problemas] == [
        "Linha 2: débito e crédito na mesma conta (8).",
        "Linha 3: valor “0” inválido (maior que zero, vírgula decimal, ex.: 150,17).",
        "Linha 4: valor “1.234,56” inválido (maior que zero, vírgula decimal, ex.: 150,17).",
        "Linha 5: tem 11 campos em vez de 10 (há “;” no complemento?).",
        "Linha 6: data 03/09/2026 fora do período exportado.",
        "Linha 7: a conta débito 353 – DESPESAS GERAIS é sintética (grupo): use uma conta analítica.",
        "Linha 8: a conta débito 999 não existe no plano de contas desta empresa.",
        "Linha 9: débito e crédito em branco.",
        "Linha 10: código da empresa 231 diferente de 230.",
        "Linha 11: data “31/02/2026” inválida (use dd/mm/aaaa).",
    ]
    assert conferir_txt(b"03/08/2026;355;8;10;;LF SEM CR;1;230;;\n")[0].texto.startswith("O arquivo tem de usar")
    assert conferir_txt(b"03/08/2026;\x81\r\n")[0].texto.startswith("O arquivo não está em Windows-1252")


@pytest.mark.amostras
def test_modelo_real_do_escritorio():
    """O lanctos.txt real de 2026 (já importado no Domínio): sem as 3 linhas com erro, o sistema gera igual,
    byte a byte; e a conferência com o plano real acha exatamente os 3 erros."""
    from app.servicos.plano import ler_plano

    modelo = AMOSTRAS / "PLANILHA EXPORTAÇÃO" / "modelo exemplar da exportacao.txt"
    plano = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    if not (modelo.exists() and plano.exists()):
        pytest.skip("AMOSTRAS/ não está neste computador")
    conteudo = modelo.read_bytes()
    lido = ler_plano(plano.read_bytes(), plano.name)
    contas = {c.reduzido: ContaContabil(reduzido=c.reduzido, descricao=c.descricao, tipo=c.tipo, ativa=True)
              for c in lido.contas}  # fmt: skip
    problemas = conferir_txt(conteudo, contas, date(2026, 1, 1), date(2026, 12, 31), 230)
    print("\n" + "\n".join(p.texto for p in problemas))
    assert len(problemas) == 3
    assert {"10595.", "28/01//2026", "28/01//2027"} == {
        trecho for p in problemas for trecho in ("10595.", "28/01//2026", "28/01//2027") if trecho in p.texto
    }
    boas = sem_as_linhas(conteudo, {p.linha for p in problemas})
    assert gerar_txt(ler_txt(boas), 230) == boas
