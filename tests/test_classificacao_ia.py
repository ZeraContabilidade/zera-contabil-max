"""IA no que as regras não resolveram: só pendentes e amarelas, resposta conferida (conta existe, é analítica,
não é a do banco), não pergunta de novo e sem IA nada muda. Sem custo: IA falsa."""

import re
from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import ContaContabil, MovimentoExtrato
from app.servicos.classificacao import classificar
from app.servicos.classificacao_ia import classificar_com_ia, montar_contexto
from app.servicos.extratos import importar_extrato
from tests.test_classificacao import empresa  # noqa: F401 — mesma empresa de teste (histórico + contas-chave)

pytestmark = pytest.mark.banco
AGOSTO = (date(2026, 8, 1), date(2026, 8, 31))


def responder(contas: dict[str, tuple[int, int]]):
    """IA falsa: para cada linha, procura um pedaço do texto em `contas` → (reduzido, confiança)."""

    def resposta(pedido):
        if pedido.finalidade != "classificacao":
            return None
        itens = []
        for numero, texto in re.findall(r"^(\d+)\. (.*)$", pedido.pergunta, re.MULTILINE):
            conta, confianca = next((v for trecho, v in contas.items() if trecho in texto), (0, 0))
            item = {"id": int(numero), "conta": conta, "favorecido": "FAVORECIDO DA IA", "natureza": "natureza da ia"}
            itens.append(item | {"confianca": confianca, "justificativa": "porque sim"})
        return {"itens": itens}

    return resposta


def sugestao(sessao, complemento):
    return sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == complemento)).sugestao


def test_ia_resolve_o_que_sobrou_e_a_resposta_e_conferida(empresa, sessao, ia_falsa):  # noqa: F811
    ia_falsa.respostas = responder(
        {"FULANO DESCONHECIDO": (359, 92), "INTERMEDIADORA": (10594, 95), "Pacote": (535, 99)}
    )
    importar_extrato(sessao, empresa, "cc.pdf", b"%PDF-falso", None)
    resultado = classificar_com_ia(sessao, empresa, None, *AGOSTO)
    sessao.commit()

    fulano = sugestao(sessao, "FULANO DESCONHECIDO")
    assert (fulano.status, fulano.origem, fulano.conta_debito.reduzido, fulano.conta_credito.reduzido) == (
        "APROVADO", "IA", 359, 8,
    )  # fmt: skip
    assert fulano.justificativa == "🤖 IA: porque sim"
    assert fulano.complemento.startswith("FAVORECIDO DA IA - NATUREZA DA IA")
    amarela = sugestao(sessao, "INTERMEDIADORA DE PAGAMENTO")  # as regras acharam pelo valor (75); a IA confirma (95)
    assert (amarela.status, amarela.origem, amarela.conta_debito.reduzido) == ("APROVADO", "IA", 10594)
    pergunta = ia_falsa.pedidos[-1][0].pergunta
    assert "Tarifa" not in pergunta and "MARIA SOUZA" not in pergunta  # o que já está verde não vai para a IA
    assert resultado.perguntadas == 2 and resultado.verdes == 2


def test_conta_invalida_da_ia_e_descartada(empresa, sessao, ia_falsa):  # noqa: F811
    ia_falsa.respostas = responder({"FULANO": (322, 95), "INTERMEDIADORA": (8, 99)})  # 322 = grupo
    importar_extrato(sessao, empresa, "cc.pdf", b"%PDF-falso", None)
    sessao.add(ContaContabil(empresa_id=empresa.id, reduzido=322, classificacao="322", classificacao_formatada="3.2.2",
                             descricao="DESPESAS ADMINISTRATIVAS", tipo="S", nivel=3)) if not sessao.scalar(
        select(ContaContabil).where(ContaContabil.reduzido == 322)) else None  # fmt: skip
    resultado = classificar_com_ia(sessao, empresa, None, *AGOSTO)
    assert resultado.recusadas == 2  # sintética e a própria conta do banco
    fulano = sugestao(sessao, "FULANO DESCONHECIDO")
    assert (fulano.status, fulano.origem, fulano.conta_debito, fulano.revisado_ia) == (
        "PENDENTE",
        "PENDENTE",
        None,
        True,
    )
    amarela = sugestao(sessao, "INTERMEDIADORA DE PAGAMENTO")
    assert (amarela.origem, amarela.conta_debito.reduzido) == ("VALOR", 10594)  # a resposta ruim não apaga a das regras


def test_nao_pergunta_de_novo_e_regra_nao_apaga_a_ia(empresa, sessao, ia_falsa):  # noqa: F811
    ia_falsa.respostas = responder({"FULANO DESCONHECIDO": (359, 80)})
    importar_extrato(sessao, empresa, "cc.pdf", b"%PDF-falso", None)
    classificar_com_ia(sessao, empresa, None, *AGOSTO)
    sessao.commit()
    chamadas = len(ia_falsa.pedidos)
    classificar(sessao, empresa, *AGOSTO)  # “Classificar de novo”
    assert sugestao(sessao, "FULANO DESCONHECIDO").origem == "IA"  # a resposta da IA ficou
    classificar_com_ia(sessao, empresa, None, *AGOSTO)
    assert len(ia_falsa.pedidos) == chamadas  # tudo já foi olhado pela IA: nenhuma pergunta nova (sem custo)


def test_sem_ia_nada_muda_e_a_tela_avisa(cliente, empresa, sessao):  # noqa: F811
    cliente.post(f"/empresas/{empresa.id}/extratos", files=[("arquivos", ("cc.pdf", b"%PDF-falso"))])
    assert sugestao(sessao, "FULANO DESCONHECIDO").origem == "PENDENTE"
    tela = cliente.post(f"/empresas/{empresa.id}/extratos/classificar", data={"mes": "2026-08"}, follow_redirects=True)
    assert "A IA não olhou os pendentes" in tela.text


def test_contexto_tem_plano_historico_e_favorecidos(empresa, sessao):  # noqa: F811
    contexto = montar_contexto(sessao, empresa)
    assert "PLANO DE CONTAS ANALÍTICO" in contexto and "355 | 3.2.2.04.000002 | ÁGUA E ESGOTO | DESPESA" in contexto
    assert "CONTAS QUE A EMPRESA MAIS USA NO HISTÓRICO" in contexto and "187 | SALÁRIOS E ORDENADOS A PAGAR" in contexto
    assert "FORNECEDOR | COMPANHIA DE AGUA EXEMPLO | 355" in contexto
    assert "Tarifas bancárias → 535" in contexto
