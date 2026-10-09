"""Extratos: leitor do PDF de conta corrente do BB (pela posição das palavras), conferência de saldo,
conta bancária ligada à conta contábil, anti-duplicidade e a aba Extratos."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.leitores import ExtratoLido, MovimentoLido, ler_extrato
from app.leitores.bb_conta_corrente import LeitorBBContaCorrente
from app.leitores.ferramentas import linhas, saldo_br, valor_br
from app.modelos import ContaBancaria, ContaChave, ContaContabil, Empresa, Extrato, MovimentoExtrato
from app.servicos.extratos import conferir_saldo, importar_extrato
from app.servicos.plano import ErroLeitura, importar_plano, ler_plano
from tests.conftest import AMOSTRAS, entrar
from tests.planos import criar_plano

# ---------------------------------------------------------------- PDF do BB montado palavra a palavra


def palavra(texto: str, x0: float, top: float, x1: float | None = None) -> dict:
    return {"text": texto, "x0": x0, "x1": x1 if x1 is not None else x0 + 5 * len(texto), "top": top}


def lancamento(top, data, codigo, historico, documento="", valor="", cd="", saldo="") -> list[dict]:
    palavras = [palavra(data, 53.1, top), palavra("2180", 154.1, top), palavra("99015", 193.2, top)]
    palavras.append(palavra(codigo, 225.1, top))
    x = 240.6
    for parte in historico.split():
        palavras.append(palavra(parte, x, top))
        x += 5 * len(parte) + 2
    if documento:
        palavras.append(palavra(documento, 461.1 - 5 * len(documento), top, 461.1))
    if valor:
        palavras.append(palavra(valor, 514.4 - 5 * len(valor), top, 514.4))
    if cd:
        palavras.append(palavra(cd, 516.6, top, 522.4))
    if saldo:
        palavras.append(palavra(saldo, 560.2, top))
    return palavras


def continuacao(top, texto, cd="") -> list[dict]:
    palavras, x = [], 225.1
    for parte in texto.split():
        palavras.append(palavra(parte, x, top))
        x += 5 * len(parte) + 2
    if cd:
        palavras.append(palavra(cd, 516.6, top, 522.4))
    return palavras


CABECALHO = [
    palavra("Ag.", 143.6, 215.8),
    palavra("origem", 157.9, 215.8),
    palavra("Lote", 196.5, 215.8),
    palavra("Histórico", 221.9, 215.8, 253.2),
    palavra("Documento", 423.3, 215.8, 464.3),
    palavra("Valor", 495.0, 215.8, 513.2),
    palavra("R$", 515.4, 215.8, 525.7),
    palavra("S", 566.5, 215.8, 571.9),
]
PAGINA_1 = [
    palavra("01/09/2026,", 24.0, 16.2),
    palavra("Banco", 316.8, 16.2),
    *CABECALHO,
    *lancamento(232.4, "31/07/2026", "000", "Saldo Anterior", saldo="1.000,"),
    *lancamento(249.0, "05/08/2026", "109", "Pagamento de Boleto", "80.501", "1.200,00", "D"),
    *continuacao(265.1, "ZERA ASSESSORIA EXEMPLO"),
    *lancamento(281.7, "11/08/2026", "870", "Transferência recebida", "556.882.000.051.019", "500,00"),
    *continuacao(297.7, "11/08 16:42 PREFEITURA EXEMPLO", cd="C"),  # o C caiu para a linha de baixo
    palavra("https://autoatendimento.bb.com.br/extrato", 24.0, 820.0),
]
PAGINA_2 = [  # sem cabeçalho: usa as colunas da 1ª página
    palavra("01/09/2026,", 24.0, 16.2),
    *lancamento(60.0, "12/08/2026", "144", "Pix - Enviado", "81.201", "100,00", "D", saldo="0,"),
    *continuacao(76.0, "12/08 09:30 MERCADO EXEMPLO"),
    *lancamento(92.0, "31/08/2026", "999", "S A L D O", saldo="200,"),
    palavra("***", 225.1, 108.0),
    palavra("Transação", 24.0, 130.0),
]
TEXTO = (
    "01/09/2026, 08:21 Banco do Brasil\nConsultas - Extrato de conta corrente\nCliente - Conta atual\n"
    "Agência 1234-5\nConta corrente 99999-9 ASSOCIACAO EXEMPLO\nPeríodo do\n08 / 2026\nextrato\n"
)


@dataclass
class PdfFalso:
    texto: str = TEXTO
    paginas: list = field(default_factory=lambda: [PAGINA_1, PAGINA_2])
    eh_pdf: bool = True


def test_valores_e_saldo_cortado():
    assert valor_br("1.234,56") == Decimal("1234.56")
    assert valor_br("80.301") is None  # documento, não valor
    assert saldo_br("80.000,") == (Decimal("80000.00"), True)
    assert saldo_br("12,5") == (Decimal("12.50"), True)
    assert saldo_br("0,00") == (Decimal("0.00"), False)


def test_palavras_viram_linhas_pela_altura():
    resultado = linhas([palavra("B", 50, 100.4), palavra("A", 10, 100.0), palavra("C", 10, 120.0)])
    assert [[p["text"] for p in linha] for linha in resultado] == [["A", "B"], ["C"]]


def test_leitor_bb_conta_corrente_pela_posicao_das_palavras():
    leitor = LeitorBBContaCorrente()
    assert leitor.reconhece(PdfFalso())
    assert not leitor.reconhece(PdfFalso(texto="Banco do Brasil\nExtratos - Poupança"))
    lido = leitor.ler(PdfFalso())
    assert (lido.agencia, lido.numero, lido.tipo, lido.titular) == ("1234-5", "99999-9", "BANCO", "ASSOCIACAO EXEMPLO")
    assert (lido.inicio, lido.fim) == (date(2026, 8, 1), date(2026, 8, 31))
    assert (lido.saldo_inicial, lido.saldo_final, lido.saldo_cortado) == (Decimal("1000"), Decimal("200"), True)
    assert [(m.historico, m.complemento, m.documento, m.valor, m.sentido, m.codigo) for m in lido.movimentos] == [
        ("Pagamento de Boleto", "ZERA ASSESSORIA EXEMPLO", "80.501", Decimal("1200.00"), "SAIDA", "109"),
        ("Transferência recebida", "PREFEITURA EXEMPLO", "556.882.000.051.019", Decimal("500.00"), "ENTRADA", "870"),
        ("Pix - Enviado", "MERCADO EXEMPLO", "81.201", Decimal("100.00"), "SAIDA", "144"),
    ]
    assert not lido.avisos


def test_arquivo_que_nao_e_extrato_conhecido():
    with pytest.raises(ErroLeitura, match="Não reconheci o extrato"):
        ler_extrato("planilha.txt", b"qualquer coisa")


@pytest.mark.parametrize(
    ("inicial", "final", "cortado", "esperado"),
    [
        ("1000", "200", False, ("CONFERE", Decimal("0"))),
        ("1000", "250", False, ("DIFERENCA", Decimal("50"))),
        ("1000", "200", True, ("CONFERE", Decimal("0"))),
        ("1000", "200.90", True, ("CONFERE", Decimal("0"))),  # centavos cortados: confere até R$ 1,00
        ("1000", "300", True, ("DIFERENCA", Decimal("100"))),
        ("1000", None, False, ("SEM_SALDO", None)),
    ],
)
def test_conferencia_do_saldo(inicial, final, cortado, esperado):
    lido = ExtratoLido("x", "BB", "1", "2", "BANCO", saldo_inicial=Decimal(inicial), saldo_cortado=cortado)
    lido.saldo_final = Decimal(final) if final else None
    assert conferir_saldo(lido, Decimal("500"), Decimal("1300")) == esperado


# ---------------------------------------------------------------- importação (com banco)


def extrato_lido(movimentos, numero="12345-6", inicial="0", final=None) -> ExtratoLido:
    lido = ExtratoLido(
        leitor="Banco do Brasil — conta corrente (PDF)",
        banco="Banco do Brasil",
        agencia="1234-5",
        numero=numero,
        tipo="BANCO",
        titular="ASSOCIACAO EXEMPLO",
        saldo_inicial=Decimal(inicial),
        movimentos=movimentos,
    )
    saldo = Decimal(inicial) + sum(m.valor if m.sentido == "ENTRADA" else -m.valor for m in movimentos)
    lido.saldo_final = Decimal(final) if final is not None else saldo
    lido.inicio, lido.fim = min(m.data for m in movimentos), max(m.data for m in movimentos)
    return lido


def mov(dia, valor, sentido="SAIDA", historico="Pagamento de Boleto", complemento="FORNECEDOR EXEMPLO", doc="1"):
    return MovimentoLido(date(2026, 8, dia), Decimal(valor), sentido, historico, complemento, doc)


AGOSTO = [mov(5, "100.00"), mov(5, "100.00"), mov(11, "800.00", "ENTRADA", "Transferência recebida", "PREFEITURA")]


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
def leitura(monkeypatch):
    """Faz o leitor devolver o extrato combinado no teste (arquivos .pdf); os outros passam pelo leitor real."""
    combinado = {}

    def falso(nome, conteudo):
        return combinado[nome] if nome in combinado else ler_extrato(nome, conteudo)

    monkeypatch.setattr("app.servicos.extratos.ler_extrato", falso)
    return combinado


@pytest.mark.banco
def test_importar_cria_a_conta_bancaria_ligada_a_conta_contabil_e_nao_duplica(empresa, sessao, leitura):
    leitura["agosto.pdf"] = extrato_lido(AGOSTO, final="600")
    extrato = importar_extrato(sessao, empresa, "agosto.pdf", b"%PDF-falso", None)
    sessao.commit()
    conta = sessao.scalar(select(ContaBancaria))
    assert conta.rotulo == "Banco do Brasil · ag. 1234-5 · conta corrente 12345-6"
    assert conta.conta_chave.conta.reduzido == 8  # “BCO BRASIL CC 12345-6” no plano
    assert (extrato.conferencia, extrato.entradas, extrato.saidas) == ("CONFERE", Decimal("800"), Decimal("200"))
    assert sessao.scalar(select(func.count()).select_from(MovimentoExtrato)) == 3  # dois boletos iguais: são dois

    # o mesmo extrato de novo e um período que se sobrepõe: só o que é novo entra
    leitura["agosto de novo.pdf"] = extrato_lido(AGOSTO, final="600")
    assert importar_extrato(sessao, empresa, "agosto de novo.pdf", b"%PDF-2", None).importacao.resumo["novos"] == 0
    leitura["meio.pdf"] = extrato_lido([*AGOSTO[1:], mov(20, "50.00")], inicial="0", final="0")
    resumo = importar_extrato(sessao, empresa, "meio.pdf", b"%PDF-3", None).importacao.resumo
    assert (resumo["novos"], resumo["repetidos"]) == (1, 2)  # só o dia 20 é novo
    sessao.commit()
    assert sessao.scalar(select(func.count()).select_from(MovimentoExtrato)) == 4
    assert sessao.scalar(select(func.count()).select_from(ContaBancaria)) == 1


@pytest.mark.banco
def test_usa_a_conta_chave_que_ja_existia(empresa, sessao, leitura):
    itau = sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == 9))
    sessao.add(ContaChave(empresa_id=empresa.id, tipo="BANCO", referencia="BB conta 12345-6", conta_id=itau.id,
                          origem="USUARIO", confianca=100))  # fmt: skip
    leitura["agosto.pdf"] = extrato_lido(AGOSTO)
    importar_extrato(sessao, empresa, "agosto.pdf", b"%PDF-falso", None)
    assert sessao.scalar(select(ContaBancaria)).conta_chave.conta.reduzido == 9  # a escolha do usuário vale


@pytest.mark.banco
def test_saldo_que_nao_confere_e_conta_sem_conta_contabil_avisam(empresa, sessao, leitura):
    leitura["agosto.pdf"] = extrato_lido(AGOSTO, numero="777-1", final="999")
    extrato = importar_extrato(sessao, empresa, "agosto.pdf", b"%PDF-falso", None)
    assert extrato.conferencia == "DIFERENCA" and extrato.diferenca == Decimal("399")
    textos = [aviso["texto"] for aviso in extrato.importacao.avisos]
    assert any("Não encontrei no plano a conta contábil" in t for t in textos)
    assert any("O saldo não confere" in t for t in textos)


@pytest.mark.banco
def test_conta_de_outra_empresa_e_recusada(empresa, sessao, leitura):
    outra = Empresa(codigo_dominio=231, nome_curto="Outra Creche")
    sessao.add(outra)
    sessao.commit()
    criar_plano(sessao, outra)
    leitura["agosto.pdf"] = extrato_lido(AGOSTO)
    importar_extrato(sessao, outra, "agosto.pdf", b"%PDF-falso", None)
    sessao.commit()
    with pytest.raises(ErroLeitura, match="que é da empresa Outra Creche"):
        importar_extrato(sessao, empresa, "agosto.pdf", b"%PDF-falso", None)


@pytest.mark.banco
def test_aba_extratos_varios_arquivos_de_uma_vez(cliente, empresa, sessao, leitura):
    leitura["agosto.pdf"] = extrato_lido(AGOSTO, final="600")
    arquivos = [("arquivos", ("agosto.pdf", b"%PDF-falso")), ("arquivos", ("notas.txt", b"nada a ver"))]
    tela = cliente.post(f"/empresas/{empresa.id}/extratos", files=arquivos, follow_redirects=True).text
    assert "agosto.pdf: Banco do Brasil · ag. 1234-5 · conta corrente 12345-6, 3 movimento(s) novo(s)" in tela
    assert "saldo confere" in tela
    assert "notas.txt: Não reconheci o extrato" in tela  # um arquivo ruim não atrapalha os outros
    assert "Extratos de agosto/2026" in tela and "PREFEITURA" in tela
    assert "8 – BCO BRASIL CC 12345-6" in tela  # conta contábil da conta bancária
    assert "3 movimentos" in tela  # barra do mês: etapa Extrato feita
    assert sessao.scalar(select(func.count()).select_from(Extrato)) == 1


@pytest.mark.banco
def test_enviar_sem_arquivo(cliente, empresa):
    tela = cliente.post(f"/empresas/{empresa.id}/extratos", follow_redirects=True).text
    assert "Escolha (ou arraste) os arquivos dos extratos" in tela


@pytest.mark.banco
@pytest.mark.amostras
def test_extrato_real_conta_corrente_bb_casa_crianca(sessao):
    """O PDF real (ago/2026): entradas = saídas = 149.568,52, saldo 0 → 0, conta 72637-0 → conta 8."""
    plano = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    pdf = AMOSTRAS / "EXTRATOS" / "EXTRATO CONTA CORRENTE.pdf"
    if not plano.exists() or not pdf.exists():
        pytest.skip("AMOSTRAS/ não está neste computador")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(plano.read_bytes(), plano.name), None)
    extrato = importar_extrato(sessao, empresa, pdf.name, pdf.read_bytes(), None)
    sessao.commit()
    assert extrato.conferencia == "CONFERE" and extrato.saldo_cortado
    assert extrato.entradas == extrato.saidas == Decimal("149568.52")
    assert extrato.importacao.resumo["novos"] == 49
    assert extrato.conta_bancaria.conta_chave.conta.reduzido == 8
    sabesp = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == "SABESP"))
    assert (sabesp.historico, sabesp.valor, sabesp.sentido) == ("Pgto conta água", Decimal("600.35"), "SAIDA")


# ---------------------------------------------------------------- poupança do BB


def linha_de(top, *palavras_x) -> list[dict]:
    """linha_de(234.0, ("03/08/2026", 50), ("100,00", 503, 527)) — (texto, x0) ou (texto, x0, x1)."""
    return [palavra(texto, x0, top, *resto) for texto, x0, *resto in palavras_x]


POUPANCA_PAGINA_1 = [
    *linha_de(187.0, ("Dt.", 102), ("base", 115), ("Dia", 147), ("Histórico", 168, 203),
              ("DocumentoInformações", 314, 406), ("Valor", 519, 538)),
    *linha_de(205.7, ("1.00", 547)),  # saldo anterior cortado pela impressão
    *linha_de(210.5, ("31/07/2026", 50), ("Saldo", 171), ("anterior", 194)),
    # transferência para a conta corrente: histórico e informações em 3 linhas
    *linha_de(229.2, ("141", 171), ("Transferencia", 186), ("Para", 237), ("03/08", 361), ("10:44", 383),
              ("ASSOCIACAO", 406)),
    *linha_de(234.0, ("03/08/2026", 50), ("03/08/2026", 104), ("1234-5", 279), ("99.999", 317),
              ("100,00", 503, 527), ("D", 530, 535)),
    *linha_de(238.3, ("Conta", 171), ("EXEMPLO", 361)),
    # valor na linha de cima e o C na de baixo
    *linha_de(252.8, ("601", 171), ("Transferência", 186), ("de", 237), ("12/08", 361), ("08:30", 383),
              ("ASSOCIACAO", 406), ("200,00", 500, 535)),
    *linha_de(257.6, ("12/08/2026", 50), ("12/08/2026", 104), ("12/8", 150), ("1234-5", 279), ("99.999", 317)),
    *linha_de(261.9, ("Crédito", 171), ("EXEMPLO", 361), ("C", 530, 535)),
    # rendimento numa linha só
    *linha_de(276.3, ("14/08/2026", 50), ("17/08/2026", 104), ("15/7", 150), ("737", 171), ("Juros", 187),
              ("1234-5", 279), ("10,00", 507, 527), ("C", 530, 535)),
]  # fmt: skip
POUPANCA_PAGINA_2 = [
    *linha_de(32.3, ("31/08/2026", 50), ("01/09/2026", 104), ("290", 171), ("Imposto", 187), ("De", 217),
              ("Renda", 230), ("1234-5", 279), ("2,00", 507, 527), ("D", 530, 535)),
    *linha_de(64.4, ("Saldo", 50), ("atual", 73), ("0", 563)),
    *linha_de(93.3, ("Saldo", 50), ("total", 73), ("1.11", 539)),
]  # fmt: skip
TEXTO_POUPANCA = (
    "01/09/2026, 08:23 Banco do Brasil\nExtratos - Poupança 01/09/2026 08:\n51 - POUPANÇA-OURO\nDIÁRIA\n"
    "Saldo: 1.110,00 C\nAgência / Conta 1234-5 / 99999-9\nPeríodo 01/08/2026 a 31/08/2026\n"
    "Titularidade ASSOCIACAO EXEMPLO\n"
)


def test_leitor_bb_poupanca_junta_as_linhas_de_cada_lancamento():
    from app.leitores.bb_poupanca import LeitorBBPoupanca

    arquivo = PdfFalso(texto=TEXTO_POUPANCA, paginas=[POUPANCA_PAGINA_1, POUPANCA_PAGINA_2])
    leitor = LeitorBBPoupanca()
    assert leitor.reconhece(arquivo) and not LeitorBBContaCorrente().reconhece(arquivo)
    lido = leitor.ler(arquivo)
    assert (lido.agencia, lido.numero, lido.tipo, lido.titular) == (
        "1234-5",
        "99999-9",
        "POUPANCA",
        "ASSOCIACAO EXEMPLO",
    )
    assert (lido.inicio, lido.fim) == (date(2026, 8, 1), date(2026, 8, 31))
    assert (lido.saldo_inicial, lido.saldo_inicial_visivel, lido.saldo_final) == (None, "1.00", Decimal("1110.00"))
    assert [(m.historico, m.complemento, m.documento, m.valor, m.sentido, m.codigo) for m in lido.movimentos] == [
        ("Transferencia Para Conta", "ASSOCIACAO EXEMPLO", "99.999", Decimal("100.00"), "SAIDA", "141"),
        ("Transferência de Crédito", "ASSOCIACAO EXEMPLO", "99.999", Decimal("200.00"), "ENTRADA", "601"),
        ("Juros", "", "", Decimal("10.00"), "ENTRADA", "737"),
        ("Imposto De Renda", "", "", Decimal("2.00"), "SAIDA", "290"),
    ]
    assert conferir_saldo(lido, Decimal("210"), Decimal("102")) == ("CONFERE", Decimal("0"))  # 1.002,00 começa com 1.00


def test_saldo_anterior_cortado_que_nao_bate():
    lido = ExtratoLido("x", "BB", "1", "2", "POUPANCA", saldo_final=Decimal("1110"), saldo_inicial_visivel="1.10")
    assert conferir_saldo(lido, Decimal("210"), Decimal("102")) == ("DIFERENCA", None)


def test_saldo_do_cabecalho_de_outra_data_nao_vale():
    from app.leitores.bb_poupanca import LeitorBBPoupanca

    outra_data = TEXTO_POUPANCA.replace("Saldo: 1.110,00 C", "Saldo: 5.000,00 C")
    lido = LeitorBBPoupanca().ler(PdfFalso(texto=outra_data, paginas=[POUPANCA_PAGINA_1, POUPANCA_PAGINA_2]))
    assert lido.saldo_final is None and "outra data" in lido.avisos[0].texto


@pytest.mark.banco
@pytest.mark.amostras
def test_extratos_reais_conta_corrente_e_poupanca_casa_crianca(sessao):
    """Os dois PDFs reais (ago/2026): poupança 227.494,23 → 239.233,33; as transferências batem com a CC."""
    plano = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    pdfs = [AMOSTRAS / "EXTRATOS" / "EXTRATO CONTA CORRENTE.pdf", AMOSTRAS / "EXTRATOS" / "EXTRATO POUPANÇA.pdf"]
    if not plano.exists() or not all(p.exists() for p in pdfs):
        pytest.skip("AMOSTRAS/ não está neste computador")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(plano.read_bytes(), plano.name), None)
    corrente, poupanca = (importar_extrato(sessao, empresa, p.name, p.read_bytes(), None) for p in pdfs)
    sessao.commit()

    assert poupanca.conferencia == "CONFERE" and poupanca.importacao.resumo["novos"] == 28
    assert (poupanca.saldo_inicial, poupanca.saldo_final) == (Decimal("227494.23"), Decimal("239233.33"))
    assert poupanca.conta_bancaria.tipo == "POUPANCA" and poupanca.conta_bancaria.numero == "72637-0"
    assert any("Não encontrei no plano a conta contábil" in a["texto"] for a in poupanca.importacao.avisos)

    def soma(extrato, codigo):
        return sum(
            m.valor
            for m in sessao.scalars(select(MovimentoExtrato).where(MovimentoExtrato.extrato_id == extrato.id))
            if m.codigo_banco == codigo
        )

    assert soma(poupanca, "141") == soma(corrente, "875")  # saiu da poupança = “Transferido da poupança” na CC
    assert soma(poupanca, "601") == soma(corrente, "475")  # entrou na poupança = “Aplicação Poupança” na CC
