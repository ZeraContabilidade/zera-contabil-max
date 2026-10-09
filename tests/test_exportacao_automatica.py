"""Exportação automática por empresa (§6.5): desligada por padrão; ligada, o lanctos.txt sai sozinho quando o mês
está todo aprovado e o saldo de todos os extratos confere — e só então. O Painel avisa até alguém baixar."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.leitores import ExtratoLido, MovimentoLido
from app.modelos import ContaContabil, Empresa, Exportacao, Log, MovimentoExtrato
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.exportacao_automatica import exportar_se_pronto, meses_entre, motivo_para_esperar
from app.servicos.extratos import importar_extrato
from tests.conftest import DADOS, entrar
from tests.planos import criar_plano
from tests.test_classificacao import CONTA_CORRENTE

pytestmark = pytest.mark.banco
AGOSTO = date(2026, 8, 1)
FIM_AGOSTO = date(2026, 8, 31)
AGUA, SALARIO, FULANO, SINDICATO = CONTA_CORRENTE[0], CONTA_CORRENTE[2], CONTA_CORRENTE[5], CONTA_CORRENTE[6]


def extrato(movimentos, numero="12345-6", tipo="BANCO", inicio=AGOSTO, fim=FIM_AGOSTO, erro_no_saldo="0"):
    """Extrato com saldo que confere (ou não, com `erro_no_saldo`)."""
    entradas = sum((m.valor for m in movimentos if m.sentido == "ENTRADA"), Decimal("0"))
    saidas = sum((m.valor for m in movimentos if m.sentido == "SAIDA"), Decimal("0"))
    return ExtratoLido(
        leitor="teste", banco="Banco do Brasil", agencia="1234-5", numero=numero, tipo=tipo, inicio=inicio, fim=fim,
        saldo_inicial=Decimal("10000.00"), saldo_final=Decimal("10000.00") + entradas - saidas + Decimal(erro_no_saldo),
        movimentos=movimentos,
    )  # fmt: skip


@pytest.fixture
def lidos(monkeypatch):
    arquivos: dict[str, ExtratoLido] = {}
    monkeypatch.setattr("app.servicos.extratos.ler_extrato", lambda nome, conteudo: arquivos[nome])
    return arquivos


@pytest.fixture
def empresa(sessao, criar_usuario, cliente, lidos):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste", exportacao_automatica=True)
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    importar_historico(sessao, nova, "lanctos.txt", (DADOS / "lanctos_exemplo.txt").read_bytes(), None)
    aprender(sessao, nova)
    sessao.commit()
    return nova


def importar(sessao, empresa, lidos, nome, lido):
    lidos[nome] = lido
    importar_extrato(sessao, empresa, nome, b"%PDF-falso", None)
    sessao.commit()


def fulano(sessao):
    return sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == "FULANO DESCONHECIDO")).sugestao


def test_meses_que_um_periodo_toca():
    assert meses_entre(date(2026, 7, 25), date(2026, 8, 10)) == [date(2026, 7, 1), AGOSTO]
    assert meses_entre(date(2026, 12, 20), date(2027, 1, 5)) == [date(2026, 12, 1), date(2027, 1, 1)]


def test_gera_sozinho_quando_o_ultimo_pendente_e_resolvido(cliente, empresa, sessao, lidos):
    importar(sessao, empresa, lidos, "cc.pdf", extrato([AGUA, SALARIO, FULANO, SINDICATO]))
    assert motivo_para_esperar(sessao, empresa, AGOSTO) == "1 linha(s) pendente(s) na Revisão"
    tela = cliente.get(f"/empresas/{empresa.id}", params={"aba": "exportar", "mes": "2026-08"}).text
    assert "Exportação automática ligada" in tela and "esperando: 1 linha(s) pendente(s) na Revisão" in tela

    cliente.post(f"/empresas/{empresa.id}/revisao/{fulano(sessao).id}", data={"acao": "salvar", "conta": "359"})
    exportacao = sessao.scalar(select(Exportacao))
    assert exportacao is not None and exportacao.automatica and exportacao.usuario_id is None
    assert exportacao.linhas == 4 and exportacao.baixado_em is None
    assert "(exportação automática)" in sessao.scalar(select(Log).where(Log.acao == "EXPORTAR")).detalhe

    painel = cliente.get("/painel", params={"mes": "2026-08"}).text
    assert "Prontos para importar no Domínio (1)" in painel and "agosto/2026 pronto para importar" in painel
    assert "🤖 sozinho" in painel
    aba = cliente.get(f"/empresas/{empresa.id}", params={"aba": "exportar", "mes": "2026-08"}).text
    assert "🤖 gerado sozinho" in aba and "novo — ainda não baixado" in aba

    cliente.get(f"/empresas/{empresa.id}/exportacoes/{exportacao.id}/lanctos.txt")  # alguém baixou
    sessao.refresh(exportacao)
    assert exportacao.baixado_em is not None
    assert "Prontos para importar" not in cliente.get("/painel", params={"mes": "2026-08"}).text


def test_desligada_nao_gera(cliente, empresa, sessao, lidos):
    empresa.exportacao_automatica = False
    sessao.commit()
    importar(sessao, empresa, lidos, "cc.pdf", extrato([AGUA, SALARIO, FULANO, SINDICATO]))
    cliente.post(f"/empresas/{empresa.id}/revisao/{fulano(sessao).id}", data={"acao": "salvar", "conta": "359"})
    assert sessao.scalar(select(Exportacao)) is None
    assert motivo_para_esperar(sessao, empresa, AGOSTO) == "exportação automática desligada"


def test_ao_enviar_o_extrato_ja_todo_aprovado(cliente, empresa, sessao, lidos):
    lidos["cc.pdf"] = extrato([AGUA, SALARIO, SINDICATO])
    tela = cliente.post(
        f"/empresas/{empresa.id}/extratos", files=[("arquivos", ("cc.pdf", b"%PDF-falso"))], follow_redirects=True
    ).text
    assert "Exportação automática: o lanctos.txt de agosto/2026 foi gerado sozinho (3 lançamento(s))" in tela


@pytest.mark.parametrize(
    ("lido", "motivo"),
    [
        (extrato([AGUA, SALARIO, SINDICATO], erro_no_saldo="10.00"), "o saldo do extrato de Banco do Brasil · ag. "
         "1234-5 · conta corrente 12345-6 não conferiu"),
        (extrato([AGUA, SALARIO, SINDICATO], fim=date(2026, 8, 20)), "o extrato de Banco do Brasil · ag. 1234-5 · "
         "conta corrente 12345-6 vai só até 20/08"),
    ],
)  # fmt: skip
def test_extrato_que_nao_fecha_o_mes_nao_gera(empresa, sessao, lidos, lido, motivo):
    importar(sessao, empresa, lidos, "cc.pdf", lido)
    assert motivo_para_esperar(sessao, empresa, AGOSTO) == motivo
    assert exportar_se_pronto(sessao, empresa, AGOSTO) is None


def test_falta_o_extrato_de_uma_conta_do_mes_anterior(empresa, sessao, lidos):
    julho = MovimentoLido(date(2026, 7, 31), Decimal("1.00"), "ENTRADA", "Juros")
    poupanca = extrato([julho], numero="99999-9", tipo="POUPANCA", inicio=date(2026, 7, 1), fim=date(2026, 7, 31))
    importar(sessao, empresa, lidos, "poupanca_julho.pdf", poupanca)
    importar(sessao, empresa, lidos, "cc.pdf", extrato([AGUA, SALARIO, SINDICATO]))
    motivo = motivo_para_esperar(sessao, empresa, AGOSTO)
    assert motivo.startswith("falta o extrato de Banco do Brasil · ag. 1234-5 · poupança 99999-9")


def test_mes_reaberto_so_a_mao(cliente, empresa, sessao, lidos):
    importar(sessao, empresa, lidos, "cc.pdf", extrato([AGUA, SALARIO, SINDICATO]))
    exportacao = exportar_se_pronto(sessao, empresa, AGOSTO)
    sessao.commit()
    cliente.post(f"/empresas/{empresa.id}/exportacoes/{exportacao.id}/reabrir", data={"motivo": "Conferir salário"})
    agua = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.valor == AGUA.valor)).sugestao
    cliente.post(f"/empresas/{empresa.id}/revisao/{agua.id}", data={"acao": "salvar", "conta": "355"})
    assert len(sessao.scalars(select(Exportacao)).all()) == 1  # não gerou de novo sozinho
    assert motivo_para_esperar(sessao, empresa, AGOSTO) == "mês reaberto pelo Supervisor: gere o arquivo à mão"


def test_ligar_no_cadastro_com_o_mes_pronto(cliente, empresa, sessao, lidos):
    empresa.exportacao_automatica = False
    sessao.commit()
    importar(sessao, empresa, lidos, "cc.pdf", extrato([AGUA, SALARIO, SINDICATO]))
    cliente.get(f"/empresas/{empresa.id}", params={"mes": "2026-08"})  # o mês da tela
    dados = {"codigo_dominio": "230", "nome_curto": "Creche Teste", "modelo_complemento": empresa.modelo_complemento}
    tela = cliente.post(f"/empresas/{empresa.id}", data={**dados, "exportacao_automatica": "on"}, follow_redirects=True)
    assert "foi gerado sozinho" in tela.text
    sessao.expire_all()
    assert sessao.get(Empresa, empresa.id).exportacao_automatica
    assert sessao.scalar(select(Exportacao)).automatica
    assert sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == 355)) is not None
