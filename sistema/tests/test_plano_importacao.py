"""Importação do plano pela tela: banco, arquivo original guardado, reimportação, cópia e busca."""

import hashlib
from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import ArquivoOriginal, ContaContabil, Empresa, Importacao, Log, Papel
from tests.conftest import DADOS, PASTA_ARQUIVOS_TESTE, entrar

pytestmark = pytest.mark.banco

TXT = (DADOS / "plano_exemplo.txt").read_bytes()


@pytest.fixture
def empresa(sessao, criar_usuario, cliente):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    return nova


def enviar(cliente, empresa, conteudo=TXT, nome="contas crianca.csv"):
    return cliente.post(f"/empresas/{empresa.id}/plano", files={"arquivo": (nome, conteudo)}, follow_redirects=True)


def contas(sessao, empresa, so_ativas=True):
    consulta = select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)
    if so_ativas:
        consulta = consulta.where(ContaContabil.ativa)
    return {c.reduzido: c for c in sessao.scalars(consulta)}


def test_importar_grava_contas_guarda_o_original_e_registra(cliente, empresa, sessao):
    resposta = enviar(cliente, empresa)
    assert "Plano de contas importado (TXT do Domínio): 32 contas (13 analíticas)." in resposta.text
    assert "Há 2 aviso(s) sobre o plano" in resposta.text

    gravadas = contas(sessao, empresa)
    assert len(gravadas) == 32
    assert gravadas[8].classificacao_formatada == "1.1.1.02.000001"
    assert gravadas[355].rotulo == "355 – ÁGUA E ESGOTO"

    arquivo = sessao.scalar(select(ArquivoOriginal))
    assert arquivo.tipo == "PLANO" and arquivo.nome_original == "contas crianca.csv"
    assert arquivo.sha256 == hashlib.sha256(TXT).hexdigest()
    assert (PASTA_ARQUIVOS_TESTE / arquivo.chave).read_bytes() == TXT  # original guardado intacto
    assert arquivo.expira_em.year - date.today().year == 5

    importacao = sessao.scalar(select(Importacao))
    assert importacao.arquivo_id == arquivo.id
    assert importacao.resumo["mascara"] == "1.1.1.2.6"
    assert sessao.scalar(select(Log).where(Log.acao == "IMPORTAR_PLANO")).detalhe.startswith("Creche Teste: 32")


def test_aba_mostra_resumo_avisos_e_barra_com_plano_feito(cliente, empresa):
    enviar(cliente, empresa)
    html = cliente.get(f"/empresas/{empresa.id}", params={"aba": "plano"}).text
    assert "32 contas · 13 analíticas · máscara 1.1.1.2.6" in html
    assert "aparecem em mais de uma conta" in html
    assert "1.1.1.02.000001" in html and "BCO BRASIL CC 12345-6" in html
    assert 'class="etapa-feita"' in html and "32 contas" in html  # Plano ✔ na barra do mês
    assert "Reimportar plano" in html


def test_reimportar_atualiza_desativa_e_reativa_sem_apagar(cliente, empresa, sessao):
    enviar(cliente, empresa)
    texto = TXT.decode("cp1252")
    linhas = texto.split("\r\n")
    sem_9 = [linha for linha in linhas if not linha.startswith("0000009")]  # conta 9 saiu do plano
    alterado = "\r\n".join(sem_9).replace("ÁGUA E ESGOTO ", "AGUA E ESGOTO-SABESP")
    nova = "001099932204000099" + " " * 9 + "MATERIAL PEDAGOGICO".ljust(40) + "A" + " " * 10
    resposta = enviar(cliente, empresa, (alterado + nova + "\r\n").encode("cp1252"))
    assert "32 contas (13 analíticas), 1 novas, 1 alteradas, 1 desativadas" in resposta.text

    todas = contas(sessao, empresa, so_ativas=False)
    assert len(todas) == 33  # nada foi apagado
    assert not todas[9].ativa
    assert todas[355].descricao == "AGUA E ESGOTO-SABESP"
    assert todas[10999].ativa

    html = cliente.get(f"/empresas/{empresa.id}", params={"aba": "plano"}).text
    assert "1 conta(s) não estão mais no plano e foram desativadas" in html

    resposta = enviar(cliente, empresa)  # volta o arquivo original
    assert "1 reativadas" in resposta.text
    sessao.expire_all()
    assert contas(sessao, empresa)[9].ativa


def test_mesmo_arquivo_duas_vezes_ocupa_espaco_uma_vez(cliente, empresa, sessao):
    enviar(cliente, empresa)
    enviar(cliente, empresa)
    chaves = {a.chave for a in sessao.scalars(select(ArquivoOriginal))}
    assert len(chaves) == 1


def test_copiar_plano_de_outra_empresa(cliente, empresa, sessao):
    enviar(cliente, empresa)
    outra = Empresa(codigo_dominio=231, nome_curto="Filial Teste")
    sessao.add(outra)
    sessao.commit()
    tela = cliente.get(f"/empresas/{outra.id}", params={"aba": "plano"}).text
    assert "230 – Creche Teste" in tela  # aparece na lista para copiar

    resposta = cliente.post(
        f"/empresas/{outra.id}/plano/copiar", data={"origem_id": str(empresa.id)}, follow_redirects=True
    )
    assert "Plano copiado de Creche Teste: 32 contas" in resposta.text
    assert len(contas(sessao, outra)) == 32
    assert sessao.scalar(select(Importacao).where(Importacao.empresa_id == outra.id)).arquivo_id is None


def test_arquivo_errado_nao_grava_nada_e_explica(cliente, empresa, sessao):
    resposta = enviar(cliente, empresa, b"Banco;Valor\nX;10\n", "extrato.csv")
    assert "Não reconheci as colunas" in resposta.text
    assert not contas(sessao, empresa)
    assert sessao.scalar(select(ArquivoOriginal)) is None


def test_sem_arquivo_pede_para_escolher(cliente, empresa):
    resposta = cliente.post(f"/empresas/{empresa.id}/plano", follow_redirects=True)
    assert "Escolha o arquivo do plano de contas" in resposta.text


@pytest.mark.parametrize(
    ("busca", "acha", "nao_acha"),
    [
        ("agua", "ÁGUA E ESGOTO", "ENERGIA"),  # sem acento
        ("355", "ÁGUA E ESGOTO", "ENERGIA"),  # reduzido
        ("3.2.2.04", "ENERGIA ELÉTRICA", "VALE TRANSPORTE"),  # classificação com pontos
    ],
)
def test_busca_no_plano(cliente, empresa, busca, acha, nao_acha):
    enviar(cliente, empresa)
    html = cliente.get(f"/empresas/{empresa.id}/plano/contas", params={"q": busca}).text
    assert acha in html and nao_acha not in html


def test_filtro_so_analiticas(cliente, empresa):
    enviar(cliente, empresa)
    html = cliente.get(f"/empresas/{empresa.id}/plano/contas", params={"analiticas": "1"}).text
    assert "ÁGUA E ESGOTO" in html and "DESPESAS GERAIS" not in html


@pytest.mark.parametrize("papel", [Papel.ASSISTENTE, Papel.CONTADOR])
def test_assistente_e_contador_tambem_importam(cliente, criar_usuario, sessao, papel):
    criar_usuario("ana")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    criar_usuario("bia", papel=papel)
    entrar(cliente, "bia")
    assert "Plano de contas importado" in enviar(cliente, empresa).text
