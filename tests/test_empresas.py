from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import Empresa, Log, Papel, Regime
from tests.conftest import entrar
from tests.test_cnpj_publico import RESPOSTA_ASSOCIACAO

pytestmark = pytest.mark.banco


@pytest.fixture
def supervisor_logado(cliente, criar_usuario):
    ana = criar_usuario("ana", nome="Ana Supervisora")
    entrar(cliente, "ana")
    return ana


def cadastrar(cliente, **campos):
    return cliente.post("/empresas", data=campos, follow_redirects=True)


def test_basta_o_codigo_do_dominio_para_cadastrar(cliente, supervisor_logado, sessao):
    resposta = cadastrar(cliente, codigo_dominio="230")
    assert "Empresa Empresa 230 (código 230) cadastrada." in resposta.text
    empresa = sessao.scalar(select(Empresa))
    assert empresa.codigo_dominio == 230
    assert empresa.modelo_complemento == "FAVORECIDO - CNPJ - NATUREZA - DOCUMENTO"
    assert empresa.ativa and empresa.campos_automaticos == []


def test_codigo_obrigatorio_e_sem_repeticao(cliente, supervisor_logado):
    assert "Informe o código da empresa no Domínio" in cadastrar(cliente, codigo_dominio="").text
    assert "Informe o código da empresa no Domínio" in cadastrar(cliente, codigo_dominio="23O").text
    cadastrar(cliente, codigo_dominio="230", nome_curto="Casa Criança")
    resposta = cadastrar(cliente, codigo_dominio="230")
    assert resposta.status_code == 400
    assert "O código 230 já é da empresa Casa Criança" in resposta.text


def test_cnpj_errado_ou_repetido_explica_o_problema(cliente, supervisor_logado):
    resposta = cadastrar(cliente, codigo_dominio="230", cnpj_cpf="06.101.084/0001-37")
    assert "O CNPJ/CPF 06.101.084/0001-37 não é válido" in resposta.text
    cadastrar(cliente, codigo_dominio="230", cnpj_cpf="06101084000136", nome_curto="Casa Criança")
    resposta = cadastrar(cliente, codigo_dominio="231", cnpj_cpf="06.101.084/0001-36")
    assert "já está na empresa Casa Criança (código 230)" in resposta.text


def test_cnpj_preenche_sozinho_com_selo_automatico(cliente, supervisor_logado, sessao, cnpj_responde):
    consultados = cnpj_responde(RESPOSTA_ASSOCIACAO)
    resposta = cadastrar(cliente, codigo_dominio="230", cnpj_cpf="06.101.084/0001-36")
    assert consultados == ["06101084000136"]
    assert "🤖 Preenchido pela consulta pública do CNPJ: razão social e regime." in resposta.text
    assert "🤖 automático" in resposta.text
    empresa = sessao.scalar(select(Empresa))
    assert empresa.cnpj_cpf == "06101084000136"
    assert empresa.razao_social == "ASSOCIACAO EXEMPLO DE CRECHES"
    assert empresa.regime == Regime.TERCEIRO_SETOR
    assert set(empresa.campos_automaticos) == {"razao_social", "regime"}
    assert empresa.dados_publicos["atividade"] == "Educação infantil - creche"


def test_o_que_o_usuario_digitou_nao_e_trocado_pela_consulta(
    cliente, supervisor_logado, sessao, cnpj_responde
):
    cnpj_responde(RESPOSTA_ASSOCIACAO)
    cadastrar(cliente, codigo_dominio="230", cnpj_cpf="06101084000136", razao_social="NOME DIGITADO")
    empresa = sessao.scalar(select(Empresa))
    assert empresa.razao_social == "NOME DIGITADO"
    assert empresa.campos_automaticos == ["regime"]


def test_sem_internet_cadastra_e_avisa(cliente, supervisor_logado, sessao):
    resposta = cadastrar(cliente, codigo_dominio="230", cnpj_cpf="06101084000136")
    assert "Não consegui consultar o CNPJ na internet agora" in resposta.text
    assert sessao.scalar(select(Empresa)).razao_social is None


def test_cpf_aceito_sem_consulta_publica(cliente, supervisor_logado, cnpj_responde, sessao):
    consultados = cnpj_responde(RESPOSTA_ASSOCIACAO)
    cadastrar(cliente, codigo_dominio="500", cnpj_cpf="529.982.247-25", razao_social="Produtor Rural")
    assert consultados == []
    assert sessao.scalar(select(Empresa)).documento_formatado == "529.982.247-25"


def test_editar_campo_automatico_tira_o_selo(cliente, supervisor_logado, sessao, cnpj_responde):
    cnpj_responde(RESPOSTA_ASSOCIACAO)
    cadastrar(cliente, codigo_dominio="230", cnpj_cpf="06101084000136")
    empresa = sessao.scalar(select(Empresa))
    resposta = cliente.post(
        f"/empresas/{empresa.id}",
        data={
            "codigo_dominio": "230",
            "cnpj_cpf": "06.101.084/0001-36",
            "razao_social": "CASA CRIANCA ESPERANCA",
            "nome_curto": "Casa Criança",
            "regime": "TERCEIRO_SETOR",
            "responsavel_id": str(supervisor_logado.id),
            "observacoes": "Creche conveniada",
            "modelo_complemento": "FAVORECIDO - NATUREZA - DOCUMENTO",
            "ativa": "on",
        },
        follow_redirects=True,
    )
    assert "Cadastro de Casa Criança salvo." in resposta.text
    sessao.refresh(empresa)
    assert empresa.campos_automaticos == ["regime"]  # regime não mudou: continua automático
    assert empresa.responsavel_id == supervisor_logado.id
    assert empresa.modelo_complemento == "FAVORECIDO - NATUREZA - DOCUMENTO"


def test_edicao_com_erro_mostra_o_que_foi_digitado(cliente, supervisor_logado, sessao):
    cadastrar(cliente, codigo_dominio="230")
    empresa = sessao.scalar(select(Empresa))
    resposta = cliente.post(
        f"/empresas/{empresa.id}",
        data={"codigo_dominio": "230", "razao_social": "Digitado agora", "modelo_complemento": "TEXTO;SOLTO"},
    )
    assert resposta.status_code == 400
    assert "não pode ter ponto e vírgula" in resposta.text
    assert 'value="Digitado agora"' in resposta.text


def test_desativar_empresa(cliente, supervisor_logado, sessao):
    cadastrar(cliente, codigo_dominio="230", nome_curto="Casa Criança")
    empresa = sessao.scalar(select(Empresa))
    dados = {"codigo_dominio": "230", "nome_curto": "Casa Criança", "modelo_complemento": "FAVORECIDO"}
    cliente.post(f"/empresas/{empresa.id}", data=dados)  # sem "ativa" = desmarcado
    sessao.refresh(empresa)
    assert not empresa.ativa
    assert "Inativa" in cliente.get("/").text


@pytest.mark.parametrize("papel", [Papel.ASSISTENTE, Papel.CONTADOR])
def test_so_supervisor_cadastra_e_altera_mas_todos_veem(cliente, criar_usuario, sessao, papel):
    criar_usuario("ana")
    sessao.add(Empresa(codigo_dominio=230, nome_curto="Casa Criança"))
    sessao.commit()
    empresa = sessao.scalar(select(Empresa))
    criar_usuario("bia", papel=papel)
    entrar(cliente, "bia")

    lista = cliente.get("/").text
    assert "Casa Criança" in lista and "+ Nova empresa" not in lista
    pagina = cliente.get(f"/empresas/{empresa.id}").text
    assert "Só o Supervisor altera o cadastro" in pagina and "<fieldset disabled>" in pagina
    assert cliente.get("/empresas/nova").status_code == 403
    assert cliente.post("/empresas", data={"codigo_dominio": "231"}).status_code == 403
    assert cliente.post(f"/empresas/{empresa.id}", data={"codigo_dominio": "999"}).status_code == 403


def test_busca_sem_acento_por_cnpj_e_por_codigo(cliente, supervisor_logado, sessao):
    sessao.add_all(
        [
            Empresa(codigo_dominio=230, razao_social="CASA CRIANÇA ESPERANÇA", cnpj_cpf="06101084000136"),
            Empresa(codigo_dominio=410, razao_social="PADARIA PÃO BOM LTDA"),
        ]
    )
    sessao.commit()

    def nomes(q):
        return cliente.get("/empresas/linhas", params={"q": q}).text

    assert "CASA CRIANÇA" in nomes("crianca") and "PADARIA" not in nomes("crianca")
    assert "CASA CRIANÇA" in nomes("06.101.084")
    assert "PADARIA" in nomes("410") and "CASA" not in nomes("410")
    assert "Nenhuma empresa encontrada para “xyz”" in nomes("xyz")


def test_filtro_so_as_minhas(cliente, supervisor_logado, criar_usuario, sessao):
    bia = criar_usuario("bia", papel=Papel.ASSISTENTE)
    sessao.add_all(
        [
            Empresa(codigo_dominio=230, nome_curto="Da Ana", responsavel_id=supervisor_logado.id),
            Empresa(codigo_dominio=231, nome_curto="Da Bia", responsavel_id=bia.id),
        ]
    )
    sessao.commit()
    html = cliente.get("/empresas/linhas", params={"minhas": "1"}).text
    assert "Da Ana" in html and "Da Bia" not in html


def test_mes_padrao_e_o_passado_e_fica_guardado(cliente, supervisor_logado, sessao, monkeypatch):
    monkeypatch.setattr("app.web.mes_anterior", lambda: date(2026, 9, 1))
    sessao.add(Empresa(codigo_dominio=230, nome_curto="Casa Criança"))
    sessao.commit()
    empresa = sessao.scalar(select(Empresa))
    assert "Setembro/2026" in cliente.get("/").text
    cliente.get("/", params={"mes": "2026-08"})
    assert 'value="2026-08"' in cliente.get(f"/empresas/{empresa.id}").text  # lembrou o mês escolhido


def test_pagina_da_empresa_tem_barra_do_mes_e_abas(cliente, supervisor_logado, sessao):
    sessao.add(Empresa(codigo_dominio=230, nome_curto="Casa Criança"))
    sessao.commit()
    empresa = sessao.scalar(select(Empresa))
    html = cliente.get(f"/empresas/{empresa.id}").text
    for etapa in ("Plano", "Aprendizado", "Extrato", "Revisão", "Exportado"):
        assert etapa in html
    assert 'aria-current="step"' in html  # a próxima etapa a fazer fica destacada
    assert "SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N" in html  # exemplo do complemento
    aprendizado = cliente.get(f"/empresas/{empresa.id}", params={"aba": "aprendizado"}).text
    assert "Esta parte chega nas etapas 1.7 e 1.8" in aprendizado


def test_empresa_inexistente_volta_para_a_lista(cliente, supervisor_logado):
    resposta = cliente.get("/empresas/999", follow_redirects=True)
    assert "Empresa não encontrada." in resposta.text


def test_cadastro_da_empresa_fica_no_log(cliente, supervisor_logado, sessao):
    cadastrar(cliente, codigo_dominio="230", nome_curto="Casa Criança")
    registro = sessao.scalar(select(Log).where(Log.entidade == "empresa"))
    assert registro.acao == "CRIAR"
    assert registro.usuario_id == supervisor_logado.id
    assert "Empresa nº" in cliente.get("/log").text
