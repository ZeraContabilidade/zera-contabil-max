"""Aplicação e resgate automáticos (15/10/2026): o dinheiro vai da conta corrente para a poupança e volta sem sair da
empresa — nunca é receita nem despesa. A poupança registra até 3 dias depois da conta corrente; o “BB Rende Fácil”
acontece dentro da própria conta corrente e não gera lançamento; a IA não recebe essas linhas."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.leitores import ExtratoLido, MovimentoLido
from app.modelos import ContaContabil, Empresa, MovimentoExtrato
from app.servicos.classificacao import classificar
from app.servicos.classificacao_ia import candidatas
from app.servicos.extratos import importar_extrato
from tests.conftest import entrar
from tests.planos import criar_plano


def mov(dia, valor, sentido, historico, complemento=""):
    return MovimentoLido(date(2026, 8, dia), Decimal(valor), sentido, historico, complemento)


CORRENTE = [
    mov(3, "2826.25", "ENTRADA", "Resgate Poupança", "Poupança (var.51)"),
    mov(3, "2826.25", "SAIDA", "Pix - Enviado", "FULANO DE TAL"),
    mov(3, "1918.66", "ENTRADA", "BB Rende Fácil", "Rende Facil"),
    mov(11, "90000.00", "SAIDA", "Aplicação Poupança", "Poupança (var.51)"),
    mov(20, "500.00", "ENTRADA", "Resgate Poupança", "Poupança (var.51)"),  # a poupança não registrou
]
POUPANCA = [
    mov(4, "2826.25", "SAIDA", "Resgate Automático"),  # um dia depois da conta corrente
    mov(12, "90000.00", "ENTRADA", "Aplicacao Automatica Poupanca"),
]


def _extrato(tipo, movimentos) -> ExtratoLido:
    return ExtratoLido(
        leitor="teste",
        banco="Banco do Brasil",
        agencia="1234-5",
        numero="12345-6",
        tipo=tipo,
        titular="ASSOCIACAO EXEMPLO",
        inicio=date(2026, 8, 1),
        fim=date(2026, 8, 31),
        movimentos=movimentos,
    )


@pytest.fixture
def empresa(sessao, criar_usuario, cliente, monkeypatch):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=121, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    lidos = {"cc.pdf": _extrato("BANCO", CORRENTE), "poupanca.pdf": _extrato("POUPANCA", POUPANCA)}
    monkeypatch.setattr("app.servicos.extratos.ler_extrato", lambda nome, conteudo: lidos[nome])
    for nome in lidos:
        importar_extrato(sessao, nova, nome, b"%PDF-", None)
    sessao.commit()
    return nova


def _linhas(sessao) -> dict[tuple[int, str, str], tuple]:
    """(dia, sentido, histórico) → (status, origem, débito, crédito)."""
    resultado = {}
    for m in sessao.scalars(select(MovimentoExtrato)):
        s = m.sugestao
        debito = s.conta_debito.reduzido if s.conta_debito else None
        credito = s.conta_credito.reduzido if s.conta_credito else None
        resultado[(m.data.day, m.sentido, m.historico)] = (s.status, s.origem, debito, credito)
    return resultado


@pytest.mark.banco
def test_resgate_e_aplicacao_automatica_pareiam_com_dias_de_diferenca(sessao, empresa):
    linhas = _linhas(sessao)
    # resgate: sai da poupança (11) e entra na conta corrente (8); lançado uma vez, na saída
    assert linhas[(4, "SAIDA", "Resgate Automático")] == ("APROVADO", "TRANSFERENCIA", 8, 11)
    assert linhas[(3, "ENTRADA", "Resgate Poupança")][:2] == ("IGNORADO", "TRANSFERENCIA")
    # aplicação: sai da conta corrente e entra na poupança no dia seguinte
    assert linhas[(11, "SAIDA", "Aplicação Poupança")] == ("APROVADO", "TRANSFERENCIA", 11, 8)
    assert linhas[(12, "ENTRADA", "Aplicacao Automatica Poupanca")][:2] == ("IGNORADO", "TRANSFERENCIA")
    # o pagamento do mesmo valor e do mesmo dia não é confundido com o resgate
    assert linhas[(3, "SAIDA", "Pix - Enviado")][1] != "TRANSFERENCIA"


@pytest.mark.banco
def test_rende_facil_nao_gera_lancamento_e_resgate_sem_par_fica_pendente(sessao, empresa):
    linhas = _linhas(sessao)
    assert linhas[(3, "ENTRADA", "BB Rende Fácil")][:2] == ("IGNORADO", "TRANSFERENCIA")  # não é rendimento
    assert linhas[(20, "ENTRADA", "Resgate Poupança")] == ("PENDENTE", "TRANSFERENCIA", 8, None)
    movimentos = list(sessao.scalars(select(MovimentoExtrato)))
    perguntar = {s.movimento.historico for s in candidatas(sessao, empresa, movimentos)}
    assert not perguntar & {"Resgate Poupança", "BB Rende Fácil", "Resgate Automático"}


@pytest.mark.banco
def test_classificar_de_novo_desfaz_receita_que_a_ia_deu_para_a_aplicacao(sessao, empresa):
    aplicacao = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.historico.startswith("Aplicacao Autom")))
    receita = sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == 10107))
    sugestao = aplicacao.sugestao
    sugestao.origem, sugestao.status, sugestao.conta_credito = "IA", "APROVADO", receita  # o erro de antes
    sessao.commit()
    classificar(sessao, empresa, date(2026, 8, 1), date(2026, 8, 31))
    sessao.commit()
    assert (sugestao.origem, sugestao.status) == ("TRANSFERENCIA", "IGNORADO")
