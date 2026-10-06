"""Porta de entrada da IA: liga/desliga, limites de gasto e registro de cada chamada."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import IAIndisponivel, chamar_ia, gasto_do_mes, inicio_do_mes, situacao_ia
from app.modelos import ChamadaIA, Empresa
from tests.conftest import entrar

pytestmark = pytest.mark.banco

PEDIDO = PedidoIA(
    finalidade="classificacao",
    instrucoes="Classifique.",
    pergunta="SABESP 120,00",
    esquema={"type": "object", "properties": {}, "additionalProperties": False},
)


@pytest.fixture
def empresa(sessao):
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    return nova


def gastar(sessao, valor, empresa=None, quando=None):
    chamada = ChamadaIA(
        empresa_id=empresa.id if empresa else None,
        finalidade="classificacao",
        modelo="claude-haiku-4-5",
        sucesso=True,
        custo_usd=Decimal(valor),
    )
    if quando:
        chamada.quando = quando
    sessao.add(chamada)
    sessao.commit()


def test_sem_chave_a_ia_fica_desligada_e_nada_e_cobrado(sessao):
    with pytest.raises(IAIndisponivel, match="ANTHROPIC_API_KEY está em branco"):
        chamar_ia(sessao, PEDIDO)
    assert situacao_ia(sessao).disponivel is False
    assert sessao.scalar(select(ChamadaIA)) is None


def test_chamada_com_sucesso_fica_registrada_com_tokens_e_custo(sessao, empresa, ia_falsa):
    ia_falsa.respostas["classificacao"] = {"conta": 355}
    resposta = chamar_ia(sessao, PEDIDO, empresa)
    assert resposta.dados == {"conta": 355}
    assert ia_falsa.pedidos[0][1] == "claude-haiku-4-5"  # modelo rápido por padrão

    chamada = sessao.scalar(select(ChamadaIA))
    assert chamada.sucesso and chamada.empresa_id == empresa.id
    assert (chamada.tokens_entrada, chamada.tokens_saida) == (1200, 150)
    assert chamada.custo_usd == Decimal("0.001950")  # 1200×1 + 150×5 por milhão
    assert chamada.resposta == {"conta": 355}
    assert chamada.entrada_resumo == "SABESP 120,00"


def test_pedido_forte_usa_o_modelo_forte(sessao, ia_falsa):
    ia_falsa.respostas["classificacao"] = {}
    chamar_ia(sessao, PedidoIA(**{**PEDIDO.__dict__, "forte": True}))
    assert ia_falsa.pedidos[0][1] == "claude-sonnet-5-5"


def test_erro_da_ia_fica_registrado_e_e_repassado(sessao, empresa, ia_falsa):
    ia_falsa.respostas["classificacao"] = ErroIA("A IA da Anthropic está fora do ar.")
    with pytest.raises(ErroIA, match="fora do ar"):
        chamar_ia(sessao, PEDIDO, empresa)
    chamada = sessao.scalar(select(ChamadaIA))
    assert not chamada.sucesso and "fora do ar" in chamada.erro


def test_registro_sobrevive_mesmo_se_a_tela_desistir(sessao, ia_falsa):
    ia_falsa.respostas["classificacao"] = {}
    chamar_ia(sessao, PEDIDO)
    sessao.rollback()  # a tela que chamou deu erro depois e desfez o resto
    assert sessao.scalar(select(ChamadaIA)) is not None


def test_empresa_com_ia_desligada(sessao, empresa, ia_falsa):
    empresa.ia_ligada = False
    sessao.commit()
    with pytest.raises(IAIndisponivel, match="desligada para Creche Teste"):
        chamar_ia(sessao, PEDIDO, empresa)
    assert ia_falsa.pedidos == []


def test_limite_geral_do_mes_para_a_ia(sessao, empresa, ia_falsa):
    gastar(sessao, "20.00")
    with pytest.raises(IAIndisponivel, match=r"limite mensal de gasto com IA \(US\$ 20,00\) foi atingido"):
        chamar_ia(sessao, PEDIDO, empresa)
    assert situacao_ia(sessao).motivo.startswith("Pausada")


def test_gasto_do_mes_passado_nao_conta(sessao, ia_falsa):
    gastar(sessao, "50.00", quando=inicio_do_mes() - timedelta(days=1))
    ia_falsa.respostas["classificacao"] = {}
    chamar_ia(sessao, PEDIDO)
    assert gasto_do_mes(sessao) == Decimal("0.001950")


def test_limite_proprio_da_empresa(sessao, empresa, ia_falsa):
    empresa.ia_limite_mensal_usd = Decimal("1.00")
    sessao.commit()
    gastar(sessao, "1.00", empresa)
    with pytest.raises(IAIndisponivel, match=r"limite mensal de IA de Creche Teste \(US\$ 1,00\)"):
        chamar_ia(sessao, PEDIDO, empresa)
    outra = Empresa(codigo_dominio=231)
    sessao.add(outra)
    sessao.commit()
    ia_falsa.respostas["classificacao"] = {}
    chamar_ia(sessao, PEDIDO, outra)  # as outras empresas continuam


def test_painel_so_para_supervisor_e_teste_de_conexao(cliente, criar_usuario, sessao, ia_falsa):
    from app.modelos import Papel

    criar_usuario("ana")
    criar_usuario("bia", papel=Papel.ASSISTENTE)
    entrar(cliente, "bia")
    assert cliente.get("/ia").status_code == 403
    cliente.post("/sair")

    entrar(cliente, "ana")
    html = cliente.get("/ia").text
    assert "Pronta para uso" in html and "claude-haiku-4-5" in html and "US$ 0,00" in html
    resposta = cliente.post("/ia/testar", follow_redirects=True)
    assert "✔ A IA respondeu: “Olá do teste”" in resposta.text
    assert "Testes de conexão" in resposta.text  # gasto sem empresa aparece no painel
    assert sessao.scalar(select(ChamadaIA)).finalidade == "teste"


def test_painel_sem_chave_explica_como_ligar(cliente, criar_usuario):
    criar_usuario("ana")
    entrar(cliente, "ana")
    html = cliente.get("/ia").text
    assert "Desligada" in html and "Como ligar a IA" in html


def test_modo_simulado_nao_conta_gasto(sessao, ia_falsa, monkeypatch):
    from app.config import obter_config

    monkeypatch.setattr(obter_config(), "ia_simulada", True)
    ia_falsa.respostas["classificacao"] = {}
    chamar_ia(sessao, PEDIDO)
    assert sessao.scalar(select(ChamadaIA)).custo_usd == 0


def test_teste_de_conexao_com_erro_avisa(cliente, criar_usuario, ia_falsa):
    criar_usuario("ana")
    entrar(cliente, "ana")
    ia_falsa.respostas["teste"] = ErroIA("A chave da API da Anthropic foi recusada.")
    resposta = cliente.post("/ia/testar", follow_redirects=True)
    assert "A chave da API da Anthropic foi recusada." in resposta.text
