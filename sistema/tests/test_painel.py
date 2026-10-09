"""Painel do Supervisor: todas as empresas no mês — situação, % classificado sozinho, correções à mão, IA e
exportação; filtros; só o Supervisor abre. Tela da IA: custo por linha resolvida."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modelos import ChamadaIA, Empresa, Papel, Sugestao
from app.servicos.exportacao import exportar
from app.servicos.painel import numeros_do_mes, painel
from app.servicos.revisao import decidir_em_lote
from tests.conftest import entrar
from tests.test_revisao import AGOSTO, empresa, sugestao_de  # noqa: F401 — empresa de teste com o extrato de agosto

pytestmark = pytest.mark.banco


@pytest.fixture
def outras(sessao, criar_usuario):
    carla = criar_usuario("carla", papel=Papel.ASSISTENTE, nome="Carla Assistente")
    sessao.add_all(
        [
            Empresa(codigo_dominio=901, nome_curto="Padaria Sem Extrato", responsavel_id=carla.id),
            Empresa(codigo_dominio=902, nome_curto="Mercado Inativo", ativa=False),
        ]
    )
    sessao.commit()
    return carla


def test_numeros_do_mes(empresa, sessao, cliente):  # noqa: F811
    n = numeros_do_mes(sessao, AGOSTO)[empresa.id]
    assert (n.movimentos, n.aprovados, n.pendentes, n.automaticos, n.correcoes) == (9, 4, 5, 4, 0)
    assert n.automatico == 44  # 4 de 9 saíram sozinhos neste exemplo pequeno

    fulano = sugestao_de(sessao, "FULANO DESCONHECIDO")
    cliente.post(f"/empresas/{empresa.id}/revisao/{fulano.id}", data={"acao": "salvar", "conta": "359"})
    amarela = sugestao_de(sessao, "INTERMEDIADORA DE PAGAMENTO")
    cliente.post(f"/empresas/{empresa.id}/revisao/{amarela.id}", data={"acao": "aprovar"})
    n = numeros_do_mes(sessao, AGOSTO)[empresa.id]
    # aprovar ou corrigir à mão não conta como “sozinho”; a correção é contada
    assert (n.aprovados, n.pendentes, n.automaticos, n.correcoes, n.automatico) == (6, 3, 4, 1, 44)


def test_painel_com_filtros(empresa, outras, sessao, cliente):  # noqa: F811
    tela = cliente.get("/painel", params={"mes": "2026-08"}).text
    assert "Painel do Supervisor" in tela and "Creche Teste" in tela and "Padaria Sem Extrato" in tela
    assert "Mercado Inativo" not in tela  # só empresas ativas
    assert "44%" in tela and "Carla Assistente" in tela
    assert f'href="/empresas/{empresa.id}?aba=revisao&mes=2026-08"' in tela  # leva à etapa onde parou

    so_carla = cliente.get("/painel", params={"mes": "2026-08", "responsavel": outras.id}).text
    assert "Padaria Sem Extrato" in so_carla and "Creche Teste" not in so_carla

    # a Creche fecha o mês: ignora as pendentes e exporta → sai do filtro “só as que ainda têm o que fazer”
    pendentes = sessao.scalars(select(Sugestao.id).where(Sugestao.status == "PENDENTE")).all()
    decidir_em_lote(sessao, empresa, list(pendentes), "ignorar", None, None)
    exportar(sessao, empresa, AGOSTO, None, None)
    sessao.commit()
    resultado = painel(sessao, AGOSTO, so_pendencia=True)
    assert [linha.empresa.nome for linha in resultado.linhas] == ["Padaria Sem Extrato"] and resultado.concluidas == 1
    tela = cliente.get("/painel", params={"mes": "2026-08"}).text
    assert "com agosto/2026 concluído" in tela and "linha(s)" in tela  # quem exportou e quantas linhas


def test_so_o_supervisor_abre_o_painel(empresa, outras, cliente):  # noqa: F811
    entrar(cliente, "carla")
    assert cliente.get("/painel").status_code == 403
    assert 'href="/painel"' not in cliente.get("/").text  # o menu nem mostra


def test_custo_por_linha_resolvida_pela_ia(empresa, sessao, cliente):  # noqa: F811
    for custo in ("0.030000", "0.015000"):
        sessao.add(ChamadaIA(empresa_id=empresa.id, finalidade="classificacao", modelo="teste", sucesso=True,
                             custo_usd=Decimal(custo)))  # fmt: skip
    for texto in ("FULANO DESCONHECIDO", "MERCEARIA ZETA"):
        sugestao = sugestao_de(sessao, texto)
        sugestao.origem, sugestao.status = "IA", "APROVADO"
    sessao.commit()
    tela = cliente.get("/ia").text
    assert "O que a IA resolveu — desde o início" in tela
    linha = tela.split("O que a IA resolveu")[1].split("</tr>")[1]
    assert "Creche Teste" in linha and "US$ 0,0450" in linha and "US$ 0,0225" in linha  # 2 linhas → metade cada
    assert numeros_do_mes(sessao, date(2026, 8, 1))[empresa.id].pela_ia == 2
