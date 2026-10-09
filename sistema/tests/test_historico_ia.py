"""IA no histórico: o que as regras não separam (um lado só, histórico fora do modelo) e contas-chave
ajustadas pela prática da empresa. Sem custo: usa a IA falsa."""

import re

import pytest
from sqlalchemy import select

from app.modelos import ContaChave, ContaContabil, Empresa, LancamentoHistorico, Padrao
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.historico_ia import contar_pendentes, revisar_historico
from tests.conftest import entrar
from tests.diarios import montar_diario
from tests.planos import criar_plano

pytestmark = pytest.mark.banco

# Diário impresso só com algumas contas: nada aqui está no modelo “FAVORECIDO - NATUREZA - DOC”
SALARIOS = ("2.1.5.01.000001", "SALÁRIOS E ORDENADOS A PAGAR")
RENDIMENTOS = ("4.6.1.02.000001", "RENDIMENTOS C/APLIC FINANC")
PAPELARIA = ("2.1.3.01.000193", "PAPELARIA CENTRAL")
DIARIO = montar_diario(
    [
        ("15/03/2026", *SALARIOS, "PAGTO FOLHA MARIA SOUZA", "D", "1000.00"),
        ("31/03/2026", *SALARIOS, "REMUNERACOES CONF. FOLHA DE PAGAMENTO REF. 03/2026", "C", "1909.04"),
        ("31/03/2026", *RENDIMENTOS, "RENDIMENTO APLICAÇÃO FINANCEIRA", "C", "481.93"),
        ("10/04/2026", *PAPELARIA, "AQUISICAO CONFORME NOTA FISCAL", "C", "100.00"),
        ("20/04/2026", *PAPELARIA, "AQUISICAO CONFORME NOTA FISCAL", "C", "120.00"),
        ("30/04/2026", *RENDIMENTOS, "RENDIMENTO APLICAÇÃO FINANCEIRA", "C", "502.10"),
        ("30/04/2026", *PAPELARIA, "AQUISICAO CONFORME NOTA FISCAL", "C", "130.00"),
    ]
)
# pagamento pelo banco com histórico fora do modelo (sem “ - ”)
LANCTOS = "10/04/2026;355;8;99,9;;PAGTO SABESP REF CONTA AGUA 44.555.666/0001-81;1;230;;\r\n".encode("cp1252")


def responder(pedido):
    """IA falsa: decide pelo texto de cada item, como a de verdade faria."""
    if pedido.finalidade != "historico_ia":
        return {"perfil": "Creche de teste."}
    itens = []
    for numero, historico in re.findall(r"^(\d+)\. .*histórico: “(.*)”$", pedido.pergunta, re.MULTILINE):
        item = {"id": int(numero), "bancario": False, "favorecido": "", "cnpj_cpf": "", "natureza": ""}
        if "MARIA SOUZA" in historico:  # CNPJ inventado (não está no texto): o sistema descarta
            item.update(bancario=True, favorecido="Maria Souza", natureza="salário mensal", cnpj_cpf="11222333000181")
        elif "RENDIMENTO" in historico:
            item.update(bancario=True, favorecido="RENDIMENTO APLICACAO FINANCEIRA", natureza="RENDIMENTO")
        elif "SABESP" in historico:
            item.update(bancario=True, favorecido="SABESP", natureza="CONTA DE AGUA", cnpj_cpf="44555666000181")
        itens.append(item)
    return {"itens": itens}


@pytest.fixture
def empresa(sessao, criar_usuario, cliente):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    return nova


def enviar(cliente, empresa, conteudo, nome):
    return cliente.post(f"/empresas/{empresa.id}/historico", files={"arquivo": (nome, conteudo)}, follow_redirects=True)


def lancamento(sessao, comeco) -> LancamentoHistorico:
    return sessao.scalar(select(LancamentoHistorico).where(LancamentoHistorico.historico.like(f"{comeco}%")))


def test_ia_decide_o_que_passou_pelo_banco_e_separa_o_favorecido(cliente, empresa, sessao, ia_falsa):
    ia_falsa.respostas = responder
    enviar(cliente, empresa, LANCTOS, "lanctos.txt")
    tela = enviar(cliente, empresa, DIARIO, "Diário.xlsx").text
    assert "🤖 A IA revisou" in tela
    sessao.expire_all()

    maria = lancamento(sessao, "PAGTO FOLHA MARIA")
    assert (maria.sentido, maria.favorecido, maria.natureza) == ("SAIDA", "MARIA SOUZA", "SALÁRIO MENSAL")
    assert maria.cnpj_cpf is None  # a IA “inventou” um CNPJ que não está no histórico
    assert lancamento(sessao, "RENDIMENTO APLIC").sentido == "ENTRADA"
    assert lancamento(sessao, "REMUNERACOES").sentido == "OUTRO"  # provisão da folha
    assert lancamento(sessao, "AQUISICAO").sentido == "OUTRO"  # nota fiscal a pagar
    sabesp = lancamento(sessao, "PAGTO SABESP")
    assert (sabesp.favorecido, sabesp.cnpj_cpf, sabesp.natureza) == ("SABESP", "44555666000181", "CONTA DE AGUA")

    fornecedor = sessao.scalar(select(Padrao).where(Padrao.tipo == "FORNECEDOR", Padrao.chave == "SABESP"))
    assert fornecedor.conta.reduzido == 355
    assert sessao.scalar(select(Padrao).where(Padrao.tipo == "CLIENTE", Padrao.chave.like("RENDIMENTO%")))
    assert contar_pendentes(sessao, empresa) == 0


def test_historicos_iguais_vao_numa_pergunta_e_nao_se_pergunta_de_novo(empresa, sessao, ia_falsa):
    ia_falsa.respostas = responder
    importar_historico(sessao, empresa, "Diário.xlsx", DIARIO, None)
    sessao.commit()
    revisao = revisar_historico(sessao, empresa)
    sessao.commit()
    assert revisao.revisados == 7 and revisao.bancarios == 3 and revisao.restantes == 0
    pergunta = ia_falsa.pedidos[-1][0].pergunta
    assert pergunta.count("AQUISICAO CONFORME NOTA FISCAL") == 1 and "3 vez(es)" in pergunta
    chamadas = len(ia_falsa.pedidos)
    assert revisar_historico(sessao, empresa).revisados == 0
    assert len(ia_falsa.pedidos) == chamadas  # nada pendente: nenhuma chamada nova


def test_sem_ia_fica_pendente_e_o_botao_avisa(cliente, empresa, sessao):
    enviar(cliente, empresa, DIARIO, "Diário.xlsx")
    tela = cliente.get(f"/empresas/{empresa.id}", params={"aba": "aprendizado"}).text
    assert "Completar com a IA" in tela and "7 lançamento(s) que as regras não entenderam" in tela
    tela = cliente.post(f"/empresas/{empresa.id}/historico/ia", follow_redirects=True).text
    assert "A IA está desligada" in tela
    assert contar_pendentes(sessao, empresa) == 7


def test_resposta_com_erro_da_ia_nao_estraga_nada(empresa, sessao, ia_falsa):
    from app.ia.cliente import ErroIA

    ia_falsa.respostas["historico_ia"] = ErroIA("Muitas chamadas à IA em pouco tempo.")
    importar_historico(sessao, empresa, "Diário.xlsx", DIARIO, None)
    sessao.commit()
    revisao = revisar_historico(sessao, empresa)
    assert revisao.revisados == 0 and revisao.restantes == 7 and "Muitas chamadas" in revisao.aviso


# ---------------------------------------------------------------- contas-chave pelo histórico


def conta(sessao, reduzido) -> ContaContabil:
    return sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == reduzido))


def test_conta_chave_segue_a_pratica_da_empresa_mas_nao_a_escolha_do_usuario(empresa, sessao):
    sessao.add(ContaChave(empresa_id=empresa.id, tipo="RENDIMENTO", referencia="", conta_id=conta(sessao, 432).id,
                          origem="REGRA", confianca=85, justificativa="Pelo nome."))  # fmt: skip
    tarifas = "".join(
        f"{dia}/03/2026;10162;8;12,5;;TARIFA PACOTE DE SERVICOS;1;230;;\r\n" for dia in ("05", "06", "07")
    ).encode("cp1252")
    importar_historico(sessao, empresa, "Diário.xlsx", DIARIO, None)
    importar_historico(sessao, empresa, "lanctos.txt", tarifas, None)
    resultado = aprender(sessao, empresa)
    sessao.commit()

    chaves = {c.tipo: c for c in sessao.scalars(select(ContaChave).where(ContaChave.empresa_id == empresa.id))}
    assert chaves["RENDIMENTO"].conta.reduzido == 10107  # os rendimentos do histórico vão para a 10107
    assert "Pelo histórico da empresa: 2 lançamento(s)" in chaves["RENDIMENTO"].justificativa
    assert chaves["TARIFA"].conta.reduzido == 10162
    assert "Conta-chave ajustada pelo histórico" in resultado.resumo()

    chaves["RENDIMENTO"].conta_id, chaves["RENDIMENTO"].origem = conta(sessao, 432).id, "USUARIO"
    sessao.commit()
    aprender(sessao, empresa)
    sessao.commit()
    sessao.refresh(chaves["RENDIMENTO"])
    assert chaves["RENDIMENTO"].conta.reduzido == 432  # a escolha do usuário fica
