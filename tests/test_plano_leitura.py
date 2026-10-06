"""Leitura do plano de contas (sem banco): TXT do Domínio, Excel e CSV."""

import io

import openpyxl
import pytest

from app.servicos.plano import (
    ErroLeitura,
    deduzir_mascara,
    formatar_classificacao,
    ler_plano,
    texto_mascara,
)
from tests.conftest import AMOSTRAS, DADOS

TXT_EXEMPLO = (DADOS / "plano_exemplo.txt").read_bytes()


def conta(plano, reduzido):
    return next(c for c in plano.contas if c.reduzido == reduzido)


def avisos(plano) -> str:
    return " | ".join(a.texto for a in plano.avisos)


def test_txt_do_dominio_reconhecido_pelo_conteudo_mesmo_com_extensao_csv():
    plano = ler_plano(TXT_EXEMPLO, "contas crianca.csv")
    assert plano.formato == "TXT do Domínio"
    assert plano.mascara == "1.1.1.2.6"
    assert len(plano.contas) == 32  # a linha final de 9s é ignorada


def test_campos_da_conta_8_do_banco():
    c = conta(ler_plano(TXT_EXEMPLO, "plano.txt"), 8)
    assert (c.classificacao, c.classificacao_formatada, c.descricao, c.tipo, c.nivel) == (
        "11102000001",
        "1.1.1.02.000001",
        "BCO BRASIL CC 12345-6",
        "A",
        5,
    )


def test_tipo_vem_do_arquivo_e_nao_da_hierarquia():
    plano = ler_plano(TXT_EXEMPLO, "plano.txt")
    assert conta(plano, 10598).tipo == "A"  # analítica com classificação de grupo (o Domínio aceita)
    assert conta(plano, 16).tipo == "S"  # grupo sem nenhuma conta embaixo
    assert conta(plano, 10).tipo == "S"  # descrição de 40 letras encostada no tipo
    assert conta(plano, 10).descricao == "APLICAÇÕES FINANCEIRAS LIQUIDEZ IMEDIATA"


def test_avisos_de_classificacao_repetida_e_descricao_cortada():
    plano = ler_plano(TXT_EXEMPLO, "plano.txt")
    repetidas = next(a for a in plano.avisos if "mais de uma conta" in a.texto)
    assert any("3.2.2.01.000010" in item and "492" in item and "10585" in item for item in repetidas.itens)
    assert "3 classificação(ões) aparecem em mais de uma conta" in repetidas.texto
    assert "descrições têm 40 letras" in avisos(plano)


def test_tipo_invalido_e_deduzido_pela_hierarquia():
    linhas = TXT_EXEMPLO.decode("cp1252").split("\r\n")
    linhas = [
        linha[:67] + "X" + linha[68:] if linha[:7] in ("0000007", "0000355") else linha for linha in linhas
    ]
    plano = ler_plano("\r\n".join(linhas).encode("cp1252"), "plano.txt")
    assert conta(plano, 7).tipo == "S"  # tem contas embaixo
    assert conta(plano, 355).tipo == "A"
    assert "2 conta(s) sem tipo S/A válido" in avisos(plano)


def test_reduzido_repetido_fica_o_primeiro():
    texto = TXT_EXEMPLO.decode("cp1252")
    linha_355 = next(linha for linha in texto.split("\r\n") if linha.startswith("0000355"))
    repetida = linha_355[:27] + "OUTRA DESCRIÇÃO".ljust(40) + linha_355[67:]
    plano = ler_plano((texto + repetida + "\r\n").encode("cp1252"), "plano.txt")
    assert conta(plano, 355).descricao == "ÁGUA E ESGOTO"
    assert "1 código(s) reduzido(s) repetido(s)" in avisos(plano)


def test_csv_com_titulos_tipo_por_extenso_e_classificacao_com_pontos():
    csv = (
        "Reduzido;Classificação;Descrição;Tipo\n"
        "0000001;1;ATIVO;Sintética\n"
        "8;1.1.1.02.000001;BCO BRASIL CC 12345-6;Analítica\n"
        "11;1.1;ATIVO CIRCULANTE;Sintética\n"
    ).encode()
    plano = ler_plano(csv, "plano.csv")
    assert plano.formato == "CSV"
    assert conta(plano, 1).tipo == "S" and conta(plano, 8).tipo == "A"
    assert conta(plano, 8).classificacao == "11102000001"


def test_csv_sem_coluna_tipo_deduz_pela_hierarquia():
    csv = "Código;Classificação;Nome\n1;1;ATIVO\n2;11;CIRCULANTE\n3;111;CAIXA\n4;112;BANCOS\n".encode(
        "cp1252"
    )
    plano = ler_plano(csv, "plano.csv")
    assert [c.tipo for c in plano.contas] == ["S", "S", "A", "A"]


def test_excel_com_titulo_acima_do_cabecalho():
    livro = openpyxl.Workbook()
    aba = livro.active
    aba.append(["PLANO DE CONTAS - EMPRESA EXEMPLO"])
    aba.append([])
    aba.append(["Código reduzido", "Classificação", "Descrição da conta", "Tipo"])
    aba.append([1, "1", "ATIVO", "S"])
    aba.append([355, "3.2.2.04.000002", "ÁGUA E ESGOTO", "A"])
    arquivo = io.BytesIO()
    livro.save(arquivo)
    plano = ler_plano(arquivo.getvalue(), "plano.xlsx")
    assert plano.formato == "Excel"
    assert conta(plano, 355).descricao == "ÁGUA E ESGOTO"


@pytest.mark.parametrize(
    ("conteudo", "trecho"),
    [
        (b"", "está vazio"),
        (b"Banco;Valor\nX;10\n", "Não reconheci as colunas"),
        (b"Reduzido;Descricao\n", "Não encontrei nenhuma conta"),
    ],
)
def test_arquivo_que_nao_e_plano_explica_o_que_fazer(conteudo, trecho):
    with pytest.raises(ErroLeitura, match=trecho):
        ler_plano(conteudo, "qualquer.csv")


def test_mascara_ignora_classificacao_fora_do_padrao():
    classificacoes = ["1", "2", "11", "12", "1101", "1102", "11123", "110101", "110102", "1101010010001"]
    classificacoes += ["1101010010002", "110101001", "110101002", "11123001"]
    mascara = deduzir_mascara(classificacoes)
    assert texto_mascara(mascara) == "1.1.2.2.3.4"
    assert formatar_classificacao("1101010010001", mascara) == ("1.1.01.01.001.0001", 6, True)
    assert formatar_classificacao("11123", mascara) == ("1.1.12.3", 4, False)


@pytest.mark.amostras
def test_planos_reais_das_amostras():
    """Fluxo nos arquivos reais (§2.4). Pula se AMOSTRAS/ não existir (fica fora do Git)."""
    pasta = AMOSTRAS / "PLANO DE CONTAS"
    if not pasta.exists():
        pytest.skip("AMOSTRAS/ não está neste computador")
    crianca = ler_plano((pasta / "contas crianca.csv").read_bytes(), "contas crianca.csv")
    assert (crianca.mascara, len(crianca.contas)) == ("1.1.1.2.6", 1190)
    assert sum(c.tipo == "A" for c in crianca.contas) == 871
    assert conta(crianca, 8).descricao == "BCO BRASIL CC 72637-0"
    assert "22 classificação(ões) aparecem em mais de uma conta" in avisos(crianca)

    outra = ler_plano((pasta / "contas.txt").read_bytes(), "contas.txt")
    assert (outra.mascara, len(outra.contas)) == ("1.1.2.2.3.4", 944)
    assert "2 conta(s) com classificação fora da máscara" in avisos(outra)
