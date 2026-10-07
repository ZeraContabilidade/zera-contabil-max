"""Diário do Domínio (Excel): leitura, partidas, Diário filtrado, cadastro preenchido e lançamento que
aparece no lanctos.txt e no Diário contado uma vez só."""

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.modelos import ContaContabil, Empresa, LancamentoHistorico, Padrao
from app.servicos.aprendizado import aprender, conta_pela_classificacao, importar_historico
from app.servicos.diario import ler_diario
from app.servicos.plano import ErroLeitura, importar_plano, ler_plano
from tests.conftest import AMOSTRAS, DADOS, entrar
from tests.diarios import DIARIO_COMPLETO, DIARIO_SO_PASSIVO, montar_diario
from tests.planos import criar_plano

COMPLETO = montar_diario(DIARIO_COMPLETO)
SO_PASSIVO = montar_diario(DIARIO_SO_PASSIVO)
LANCTOS = (DADOS / "lanctos_exemplo.txt").read_bytes()


# ---------------------------------------------------------------- leitura (sem banco)


def test_le_cabecalho_e_monta_as_partidas_do_diario_completo():
    lido = ler_diario(COMPLETO)
    assert (lido.empresa, lido.cnpj) == ("ASSOCIACAO CRECHE EXEMPLO", "12345678000195")
    assert lido.periodo == "01/01/2026 - 30/06/2026"
    assert lido.completo and lido.um_lado == 0 and not lido.avisos
    assert len(lido.linhas) == 11
    folha = [p for p in lido.partidas if p.historico == "FOLHA DE PAGAMENTO 03/2026"]
    assert [(p.debito.classificacao, p.credito.classificacao, p.valor) for p in folha] == [
        ("32201000001", "21501000001", Decimal("4500.00")),
        ("32201000001", "21502000001", Decimal("500.00")),
    ]  # um débito contra dois créditos = duas partidas
    assert len(lido.partidas) == 6


def test_diario_so_com_algumas_contas_fica_com_um_lado_e_avisa():
    lido = ler_diario(SO_PASSIVO)
    assert not lido.completo
    assert len(lido.partidas) == 5 and lido.um_lado == 4
    inss = next(p for p in lido.partidas if p.debito and p.credito)  # duas linhas seguidas do mesmo lançamento
    assert inss.valor == Decimal("147.49")
    assert "TODAS as contas" in lido.avisos[0].texto
    assert lido.avisos[0].itens == ["Contas do grupo 2: 6 linha(s)"]


def test_planilha_que_nao_e_diario():
    planilha = Workbook()
    planilha.active.append(["Banco", "Valor"])
    arquivo = io.BytesIO()
    planilha.save(arquivo)
    with pytest.raises(ErroLeitura, match="não parece um Diário"):
        ler_diario(arquivo.getvalue())


def test_classificacao_repetida_decide_pela_descricao_mesmo_cortada():
    vale = ContaContabil(reduzido=492, classificacao="32201000010", descricao="VALE TRANSPORTE", tipo="A")
    rescisao = ContaContabil(
        reduzido=10585, classificacao="32201000010", descricao="DESPESA COM RESCISÃO DE CONTRATO DE TRAB", tipo="A"
    )  # o plano do Domínio corta a descrição em 40 letras
    candidatas = [vale, rescisao]
    assert conta_pela_classificacao(candidatas, "Vale Transporte") is vale
    assert conta_pela_classificacao(candidatas, "DESPESA COM RESCISÃO DE CONTRATO DE TRABALHO") is rescisao
    assert conta_pela_classificacao(candidatas, "OUTRA COISA") is None
    assert conta_pela_classificacao([vale], "nome diferente") is vale  # classificação única: basta ela


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


def enviar(cliente, empresa, conteudo, nome="Diário.xlsx"):
    return cliente.post(f"/empresas/{empresa.id}/historico", files={"arquivo": (nome, conteudo)}, follow_redirects=True)


def lancamentos(sessao) -> list[LancamentoHistorico]:
    return list(sessao.scalars(select(LancamentoHistorico).order_by(LancamentoHistorico.data, LancamentoHistorico.id)))


def reduzido(sessao, conta_id) -> int | None:
    return sessao.get(ContaContabil, conta_id).reduzido if conta_id else None


@pytest.mark.banco
def test_importar_diario_completo(cliente, empresa, sessao):
    tela = enviar(cliente, empresa, COMPLETO).text
    assert "Histórico importado: 6 lançamento(s) novo(s)." in tela
    assert "🤖 Preenchido pelo Diário: CNPJ e razão social." in tela
    sessao.refresh(empresa)
    assert (empresa.cnpj_cpf, empresa.razao_social) == ("12345678000195", "ASSOCIACAO CRECHE EXEMPLO")
    assert {"cnpj_cpf", "razao_social"} <= set(empresa.campos_automaticos)

    lidos = {
        (lanc.historico[:20], lanc.sentido, reduzido(sessao, lanc.contrapartida_id)) for lanc in lancamentos(sessao)
    }
    assert ("COMPANHIA DE AGUA EX", "SAIDA", 355) in lidos
    assert ("SINDICATO EXEMPLO 11", "SAIDA", 10595) in lidos  # classificação repetida: pela descrição
    assert ("RENDIMENTO DA POUPAN", "ENTRADA", 10107) in lidos  # poupança é do Disponível: recebimento
    assert ("FOLHA DE PAGAMENTO 0", "OUTRO", None) in lidos  # sem banco: não ensina o extrato
    assert padrao_de(sessao, "FORNECEDOR", "SINDICATO EXEMPLO").conta.reduzido == 10595


def padrao_de(sessao, tipo, chave) -> Padrao:
    return sessao.scalar(select(Padrao).where(Padrao.tipo == tipo, Padrao.chave == chave))


@pytest.mark.banco
def test_mesmo_lancamento_no_lanctos_e_no_diario_conta_uma_vez(cliente, empresa, sessao):
    enviar(cliente, empresa, LANCTOS, "lanctos.txt")
    tela = enviar(cliente, empresa, COMPLETO).text
    assert "4 lançamento(s) novo(s), 2 repetido(s) ignorado(s)" in tela  # água e FGTS de março já estavam
    agua = sessao.scalar(
        select(func.count()).where(
            LancamentoHistorico.historico.like("COMPANHIA DE AGUA%"), LancamentoHistorico.valor == Decimal("101.30")
        )
    )
    assert agua == 1
    assert "6 repetido(s) ignorado(s)" in enviar(cliente, empresa, COMPLETO).text  # reimportar o Diário


@pytest.mark.banco
def test_diario_so_do_passivo_aprende_os_pagamentos_e_o_lanctos_completa(cliente, empresa, sessao):
    tela = enviar(cliente, empresa, SO_PASSIVO).text
    assert "Histórico importado: 5 lançamento(s) novo(s)." in tela
    assert "TODAS as contas" in tela
    por_historico = {lanc.historico[:18]: lanc for lanc in lancamentos(sessao)}
    maria = por_historico["MARIA SOUZA - SALA"]
    assert (maria.sentido, reduzido(sessao, maria.contrapartida_id), maria.conta_credito_id) == ("SAIDA", 187, None)
    assert por_historico["REMUNERACOES CONF."].sentido == "OUTRO"  # provisão da folha
    assert por_historico["AQUISICAO CONFORME"].sentido == "OUTRO"  # nota fiscal a pagar
    assert por_historico["PAPELARIA CENTRAL "].sentido == "SAIDA"
    assert padrao_de(sessao, "FORNECEDOR", "PAPELARIA CENTRAL").conta.reduzido == 10574

    tela = enviar(cliente, empresa, LANCTOS, "lanctos.txt").text
    assert "1 completado(s)" in tela  # o salário de janeiro ganhou o lado do banco
    sessao.expire_all()
    salarios = sessao.scalars(
        select(LancamentoHistorico).where(LancamentoHistorico.historico.like("MARIA SOUZA%SALARIO MENSAL%"))
    ).all()
    janeiro = [lanc for lanc in salarios if lanc.data.month == 1 and lanc.data.year == 2026]
    assert len(janeiro) == 1 and reduzido(sessao, janeiro[0].conta_credito_id) == 8


@pytest.mark.banco
def test_diario_de_outra_empresa_e_recusado(cliente, empresa, sessao):
    empresa.cnpj_cpf = "98765432000198"
    sessao.commit()
    tela = enviar(cliente, empresa, COMPLETO).text
    assert "Este Diário é de ASSOCIACAO CRECHE EXEMPLO (CNPJ 12.345.678/0001-95)" in tela
    assert sessao.scalar(select(LancamentoHistorico)) is None

    outra = Empresa(codigo_dominio=231, cnpj_cpf="12345678000195")
    empresa.cnpj_cpf = None
    sessao.add(outra)
    sessao.commit()
    assert "que está cadastrado na empresa" in enviar(cliente, empresa, COMPLETO).text


@pytest.mark.banco
@pytest.mark.amostras
def test_casa_crianca_diario_real(sessao):
    """O Diário real (jan–jun/2026, impresso só com o Passivo) junto com os lanctos.txt reais."""
    plano = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    diario = AMOSTRAS / "historicos" / "Diário.xls"
    lanctos_2026 = AMOSTRAS / "PLANILHA EXPORTAÇÃO" / "modelo exemplar da exportacao.txt"
    if not all(a.exists() for a in (plano, diario, lanctos_2026)):
        pytest.skip("AMOSTRAS/ não está neste computador")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(plano.read_bytes(), plano.name), None)
    so_lanctos = importar_historico(sessao, empresa, lanctos_2026.name, lanctos_2026.read_bytes(), None)
    importacao = importar_historico(sessao, empresa, diario.name, diario.read_bytes(), None)
    resultado = aprender(sessao, empresa)
    sessao.commit()
    resumo = importacao.resumo
    print(f"\nlanctos: {so_lanctos.resumo}\nDiário: {resumo}\n" + resultado.resumo().replace("🤖 ", ""))

    assert empresa.cnpj_cpf == "06101084000136"
    assert empresa.razao_social == "CASA CRIANCA ESPERANCA NOSSA SENHORA DO MONTE BERICO"
    assert not resumo["completo"] and resumo["linhas"] == 273
    assert not [a for a in importacao.avisos if "ficaram de fora" in a["texto"]]  # toda classificação achou conta
    assert resumo["repetidos"] > 50  # os pagamentos do lanctos.txt que também estão no Diário
    zera = sessao.scalar(select(Padrao).where(Padrao.chave.like("ZERA ASSESSORIA%")))
    assert zera.conta.classificacao == "21301000190"
    assert zera.ocorrencias <= 6  # um por mês: o Diário não dobrou a contagem
