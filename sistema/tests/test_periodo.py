"""Trabalhar por período (de um mês até outro, ex.: o ano todo): telas, Revisão, parecidas, envio de extratos e um
lanctos.txt do período inteiro para importar no Domínio (pedido do usuário em 09/10/2026)."""

from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import Exportacao
from app.servicos.competencia import Periodo
from app.servicos.exportacao import conferir_txt
from app.servicos.exportacao_automatica import motivo_para_esperar
from app.servicos.extratos import importar_extrato
from app.servicos.progresso import progresso_do_mes
from app.servicos.revisao import parecidas
from tests.test_revisao import (  # noqa: F401 — mesma empresa de teste (agosto; “setembro.pdf” = o mês seguinte)
    AGOSTO,
    empresa,
    recarregar,
    sugestao_de,
)

pytestmark = pytest.mark.banco
SETEMBRO = date(2026, 9, 1)
PERIODO = {"mes": "2026-08", "ate": "2026-09"}


@pytest.fixture
def dois_meses(sessao, empresa):  # noqa: F811
    importar_extrato(sessao, empresa, "setembro.pdf", b"%PDF-falso", None)
    sessao.commit()
    return empresa


def test_tela_mostra_o_periodo_e_guarda_para_as_outras(cliente, dois_meses):
    tela = cliente.get(f"/empresas/{dois_meses.id}", params={"aba": "revisao", "filtro": "todos", **PERIODO}).text
    assert "Revisão de agosto/2026 a setembro/2026" in tela
    assert tela.count("FULANO DESCONHECIDO") >= 2  # a linha de agosto e a de setembro
    assert 'name="ate" value="2026-09"' in tela and "Um mês só" in tela
    extratos = cliente.get(f"/empresas/{dois_meses.id}", params={"aba": "extratos"}).text  # sem mês: o guardado
    assert "Extratos de agosto/2026 a setembro/2026" in extratos
    assert "agosto/2026 a setembro/2026" in cliente.get("/").text.lower()  # a lista de empresas no mesmo período
    um_mes = cliente.get(f"/empresas/{dois_meses.id}", params={"aba": "revisao", "mes": "2026-09"}).text
    assert "Revisão de setembro/2026" in um_mes and "Vários meses" in um_mes


def test_um_lanctos_txt_do_periodo_inteiro(cliente, sessao, dois_meses):
    setembro = sugestao_de(sessao, "FULANO DESCONHECIDO", mes=9)
    cliente.post(f"/empresas/{dois_meses.id}/revisao/{setembro.id}", data={"acao": "salvar", "conta": "359"})
    tela = cliente.post(
        f"/empresas/{dois_meses.id}/exportar",
        data={"mes": "2026-08_2026-09", "deixar_pendentes": "on"},
        follow_redirects=True,
    ).text
    assert "lanctos.txt gerado" in tela and "agosto/2026 a setembro/2026" in tela
    exportacao = sessao.scalar(select(Exportacao))
    assert (exportacao.competencia, exportacao.competencia_fim) == (AGOSTO, SETEMBRO)

    resposta = cliente.get(f"/empresas/{dois_meses.id}/exportacoes/{exportacao.id}/lanctos.txt")
    assert 'filename="lanctos_230_2026-08_a_2026-09.txt"' in resposta.headers["content-disposition"]
    linhas = [linha for linha in resposta.content.decode("cp1252").split("\r\n") if linha]
    assert any(linha.startswith("03/08/2026;355;") for linha in linhas)  # agosto…
    assert any(linha.startswith("04/09/2026;359;") for linha in linhas)  # …e setembro no mesmo arquivo
    assert conferir_txt(resposta.content, inicio=AGOSTO, fim=date(2026, 9, 30), codigo_empresa=230) == []
    for mes in (AGOSTO, SETEMBRO):  # cada mês do período fica com a etapa “Exportado” feita
        assert next(e for e in progresso_do_mes(sessao, dois_meses, mes) if e.chave == "exportado").situacao == "feita"
    resumo = cliente.get(f"/empresas/{dois_meses.id}/exportacoes/{exportacao.id}/resumo.xlsx")
    assert "resumo_230_2026-08_a_2026-09.xlsx" in resumo.headers["content-disposition"]

    dois_meses.exportacao_automatica = True
    sessao.commit()
    cliente.post(f"/empresas/{dois_meses.id}/exportacoes/{exportacao.id}/reabrir", data={"motivo": "conferir o ano"})
    assert recarregar(sessao, setembro).status == "APROVADO"
    assert motivo_para_esperar(sessao, dois_meses, SETEMBRO) == "mês reaberto pelo Supervisor: gere o arquivo à mão"


def test_parecidas_valem_para_o_periodo_da_tela(cliente, sessao, dois_meses):
    agosto = sugestao_de(sessao, "FULANO DESCONHECIDO")
    setembro = sugestao_de(sessao, "FULANO DESCONHECIDO", mes=9)
    cliente.get(f"/empresas/{dois_meses.id}", params={"aba": "revisao", **PERIODO})  # o período fica na tela
    resposta = cliente.post(
        f"/empresas/{dois_meses.id}/revisao/{agosto.id}",
        data={"acao": "salvar", "conta": "359"},
        headers={"HX-Request": "true"},
    )
    assert "às outras 1 linha(s) de “FULANO DESCONHECIDO” neste período?" in resposta.text
    agosto = recarregar(sessao, agosto)
    assert parecidas(sessao, agosto) == []  # num mês só, setembro ficaria de fora
    assert parecidas(sessao, agosto, Periodo(AGOSTO, SETEMBRO)) == [recarregar(sessao, setembro)]

    cliente.post(f"/empresas/{dois_meses.id}/revisao/{agosto.id}/parecidas")
    setembro = recarregar(sessao, setembro)
    assert (setembro.conta_debito.reduzido, setembro.status) == (359, "APROVADO")


def test_extrato_enviado_dentro_do_periodo_fica_no_periodo(cliente, empresa):  # noqa: F811
    cliente.get(f"/empresas/{empresa.id}", params={"aba": "extratos", **PERIODO})
    resposta = cliente.post(
        f"/empresas/{empresa.id}/extratos", files={"arquivos": ("setembro.pdf", b"%PDF-falso")}, follow_redirects=False
    )
    assert resposta.status_code == 303 and "mes=" not in resposta.headers["location"]


def test_extrato_de_outro_mes_abre_o_mes_dele(cliente, empresa):  # noqa: F811
    cliente.get(f"/empresas/{empresa.id}", params={"aba": "extratos", "mes": "2026-08"})
    resposta = cliente.post(
        f"/empresas/{empresa.id}/extratos", files={"arquivos": ("setembro.pdf", b"%PDF-falso")}, follow_redirects=False
    )
    assert resposta.headers["location"].endswith("mes=2026-09")


def test_painel_por_periodo(cliente, dois_meses):
    tela = cliente.get("/painel", params=PERIODO).text
    assert "agosto/2026 a setembro/2026" in tela and 'name="ate" value="2026-09"' in tela
