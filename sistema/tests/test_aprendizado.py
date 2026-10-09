"""Aprendizado com o histórico (lanctos.txt): leitura, padrões, ambiguidade, escolha do usuário e perfil."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modelos import ContaChave, Empresa, LancamentoHistorico, Log, Padrao
from app.servicos.aprendizado import (
    aprender,
    importar_historico,
    normalizar_natureza,
    normalizar_nome,
    separar_complemento,
)
from app.servicos.lanctos import ler_lanctos
from app.servicos.plano import ErroLeitura, importar_plano, ler_plano
from tests.conftest import AMOSTRAS, DADOS, entrar
from tests.planos import criar_plano

LANCTOS = (DADOS / "lanctos_exemplo.txt").read_bytes()


# ---------------------------------------------------------------- sem banco


@pytest.mark.parametrize(
    ("texto", "favorecido", "cnpj", "natureza", "documento"),
    [
        (
            "SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N",
            "SABESP",
            "43776517000180",
            "CONTA DE AGUA",
            "S/N",
        ),
        (
            "SINDICATO EXEMPLO 11.222.333/0001-81 - PLANO ODONTOLOGICO - S/N",
            "SINDICATO EXEMPLO",
            "11222333000181",
            "PLANO ODONTOLOGICO",
            "S/N",
        ),
        ("MARIA SOUZA  - SALARIO MENSAL  - S/N", "MARIA SOUZA", None, "SALARIO MENSAL", "S/N"),
        (
            "MERCADO MISTO LTDA - 77.888.999/0001-81 - COMPRAS - 11",
            "MERCADO MISTO LTDA",
            "77888999000181",
            "COMPRAS",
            "11",
        ),
        (
            "TRANSPORTES EXEMPLO S/A - 33.222.111/000-25 - VALE TRANSPORTE - 170",
            "TRANSPORTES EXEMPLO S/A",
            None,
            "VALE TRANSPORTE",
            "170",
        ),
        (
            "PAGAMENTO DA GUIA DE FGTS - REF S FOLHA DE MARÇO - S/N",
            "PAGAMENTO DA GUIA DE FGTS",
            None,
            "REF S FOLHA DE MARÇO",
            "S/N",
        ),
        ("TARIFA PACOTE DE SERVIÇOS", "TARIFA PACOTE DE SERVIÇOS", None, "", ""),
    ],
)
def test_separar_favorecido_cnpj_natureza_e_documento(texto, favorecido, cnpj, natureza, documento):
    partes = separar_complemento(texto)
    assert (partes.favorecido, partes.cnpj_cpf, partes.natureza, partes.documento) == (
        favorecido,
        cnpj,
        natureza,
        documento,
    )


def test_mesma_pessoa_escrita_de_jeitos_diferentes():
    assert normalizar_nome("DANIELA CORDEIRO DE OLIVEIRA") == normalizar_nome("Daniela Cordeiro Oliveira")
    assert normalizar_nome("SUPRICORP SUPRIMENTOS LTDA ") == "SUPRICORP SUPRIMENTOS"
    assert normalizar_nome("42.066.834 JULIANA DE OLIVEIRA MARQUES") == "JULIANA OLIVEIRA MARQUES"


def test_natureza_sem_mes_nem_referencia():
    assert normalizar_natureza("SALÁRIO MENSAL REF JANEIRO") == "SALARIO MENSAL"
    assert normalizar_natureza("SERVIÇOS CONTABEIS (JUNHO)") == "SERVICOS CONTABEIS"
    assert normalizar_natureza("REF S FOLHA DE MARÇO") == ""


def test_lanctos_le_e_corrige_os_erros_de_digitacao():
    linhas, avisos = ler_lanctos(LANCTOS.decode("cp1252"))
    assert len(linhas) == 23
    rescisao = next(linha for linha in linhas if "RESCISÃO" in linha.complemento)
    assert rescisao.data.isoformat() == "2026-01-28"  # “28/01//2026”
    assert any(linha.debito == 10595 and linha.valor == Decimal("247.5") for linha in linhas)  # “10595.”
    assert "2 erro(s) de digitação corrigido(s)" in avisos[0].texto


# ---------------------------------------------------------------- com banco

pytestmark_banco = pytest.mark.banco


@pytest.fixture
def empresa(sessao, criar_usuario, cliente):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    return nova


def enviar(cliente, empresa, conteudo=LANCTOS, nome="lanctos.txt"):
    return cliente.post(f"/empresas/{empresa.id}/historico", files={"arquivo": (nome, conteudo)}, follow_redirects=True)


def padrao(sessao, tipo, chave) -> Padrao:
    return sessao.scalar(select(Padrao).where(Padrao.tipo == tipo, Padrao.chave == chave))


@pytest.mark.banco
def test_importar_e_aprender(cliente, empresa, sessao):
    resposta = enviar(cliente, empresa)
    assert "Histórico importado: 23 lançamento(s) novo(s)." in resposta.text
    assert "🤖 Aprendido: 8 fornecedor(es)/favorecido(s), 0 cliente(s) e 1 palavra(s)-chave." in resposta.text
    assert "1 ficaram ambíguos" in resposta.text
    assert sessao.scalar(select(LancamentoHistorico).where(LancamentoHistorico.sentido != "SAIDA")) is None


@pytest.mark.banco
def test_salario_segue_a_pratica_mais_recente_sem_ficar_ambiguo(cliente, empresa, sessao):
    enviar(cliente, empresa)
    maria = padrao(sessao, "FORNECEDOR", "MARIA SOUZA")  # “MARIA DE SOUZA” (2025) e “MARIA SOUZA” (2026)
    assert maria.conta.reduzido == 187 and not maria.ambiguo  # 2025 → 331; 2026 → 187
    assert {c["conta"] for c in maria.detalhes["contas"]} == {187, 331}
    assert maria.ocorrencias == 4
    assert maria.detalhes["valores"] == ["2861.25", "2700.00"]  # o atual primeiro
    salario = padrao(sessao, "PALAVRA", "SALARIO MENSAL")
    assert salario.conta.reduzido == 187


@pytest.mark.banco
def test_mesmo_favorecido_contas_diferentes_pela_natureza_nao_e_ambiguo(cliente, empresa, sessao):
    enviar(cliente, empresa)
    sindicato = padrao(sessao, "FORNECEDOR", "SINDICATO EXEMPLO")
    assert not sindicato.ambiguo
    assert sindicato.cnpj_cpf == "11222333000181"
    por_natureza = sindicato.detalhes["por_natureza"]
    assert por_natureza["PLANO ODONTOLOGICO"]["conta"] == 10594
    assert por_natureza["PLANO ODONTOLOGICO"]["valores"] == ["910.00"]  # o valor identifica a natureza
    assert por_natureza["CONTRIBUICAO NEGOCIAL"]["conta"] == 10595  # inclui a linha “10595.” corrigida
    assert por_natureza["MENSALIDADE SINDICAL"]["conta"] == 10596


@pytest.mark.banco
def test_contas_diferentes_sem_motivo_fica_ambiguo_e_o_usuario_escolhe(cliente, empresa, sessao):
    enviar(cliente, empresa)
    mercado = padrao(sessao, "FORNECEDOR", "MERCADO MISTO")
    assert mercado.ambiguo
    html = cliente.get(f"/empresas/{empresa.id}", params={"aba": "aprendizado"}).text
    assert "ambíguo — escolha" in html and "1 ambíguo(s)" in html

    resposta = cliente.post(
        f"/empresas/{empresa.id}/padroes/{mercado.id}/conta",
        data={"conta": "360 – MATERIAL DE HIGIENE E LIMPEZA"},
        follow_redirects=True,
    )
    assert "agora usa 360 – MATERIAL DE HIGIENE E LIMPEZA" in resposta.text
    cliente.post(f"/empresas/{empresa.id}/aprendizado/refazer")  # recalcular não desfaz a escolha
    sessao.expire_all()
    mercado = padrao(sessao, "FORNECEDOR", "MERCADO MISTO")
    assert (mercado.conta.reduzido, mercado.origem, mercado.ambiguo) == (360, "USUARIO", False)
    alteracao = sessao.scalar(select(Log).where(Log.entidade == "padrao", Log.acao == "ALTERAR"))
    assert alteracao is not None  # a escolha do usuário fica no log


@pytest.mark.banco
def test_reimportar_o_mesmo_arquivo_nao_duplica(cliente, empresa, sessao):
    enviar(cliente, empresa)
    resposta = enviar(cliente, empresa)
    assert "0 lançamento(s) novo(s), 23 repetido(s) ignorado(s)" in resposta.text
    total = sessao.scalars(select(LancamentoHistorico)).all()
    assert len(total) == 23


@pytest.mark.banco
def test_conta_do_banco_vira_conta_chave_pelo_historico(cliente, empresa, sessao):
    enviar(cliente, empresa)
    banco = sessao.scalar(select(ContaChave).where(ContaChave.tipo == "BANCO"))
    assert (banco.referencia, banco.conta.reduzido) == ("BB conta 12345-6", 8)
    assert "Usada como banco em 23 pagamento(s)" in banco.justificativa


@pytest.mark.banco
def test_aprendizado_em_bloco_vira_um_evento_no_log(cliente, empresa, sessao):
    enviar(cliente, empresa)
    acoes = [log.acao for log in sessao.scalars(select(Log))]
    assert "IMPORTAR_HISTORICO" in acoes and "APRENDER" in acoes
    assert not sessao.scalar(select(Log).where(Log.entidade == "padrao"))  # nada de 1 linha por padrão


@pytest.mark.banco
def test_barra_do_mes_marca_aprendizado_e_tela_mostra_tudo(cliente, empresa):
    enviar(cliente, empresa)
    html = cliente.get(f"/empresas/{empresa.id}", params={"aba": "aprendizado"}).text
    assert "padrões" in html and 'class="etapa-feita"' in html
    assert "Varia pela natureza" in html and "910,00" in html
    assert "Pagamentos por conta" in html and "187 – SALÁRIOS E ORDENADOS A PAGAR" in html
    assert "2 erro(s) de digitação corrigido(s)" in html


@pytest.mark.banco
def test_desativar_e_criar_palavra_chave(cliente, empresa, sessao):
    enviar(cliente, empresa)
    agua = padrao(sessao, "FORNECEDOR", "COMPANHIA AGUA EXEMPLO")
    cliente.post(f"/empresas/{empresa.id}/padroes/{agua.id}/ativo")
    sessao.expire_all()
    assert not padrao(sessao, "FORNECEDOR", "COMPANHIA AGUA EXEMPLO").ativo

    erro = cliente.post(
        f"/empresas/{empresa.id}/padroes/palavra", data={"texto": "TARIFA", "conta": "367"}, follow_redirects=True
    )
    assert "é sintética (grupo)" in erro.text
    resposta = cliente.post(
        f"/empresas/{empresa.id}/padroes/palavra",
        data={"texto": "Tarifa pacote", "conta": "535 – TARIFA BANCÁRIA"},
        follow_redirects=True,
    )
    assert "Palavra-chave “TARIFA PACOTE” → 535 – TARIFA BANCÁRIA." in resposta.text
    assert padrao(sessao, "PALAVRA", "TARIFA PACOTE").origem == "USUARIO"


@pytest.mark.banco
def test_busca_de_favorecidos(cliente, empresa):
    enviar(cliente, empresa)
    html = cliente.get(f"/empresas/{empresa.id}/aprendizado/padroes", params={"q": "sindicato"}).text
    assert "SINDICATO EXEMPLO" in html and "MARIA" not in html
    so_ambiguos = cliente.get(f"/empresas/{empresa.id}/aprendizado/padroes", params={"ambiguos": "1"}).text
    assert "MERCADO MISTO" in so_ambiguos and "SINDICATO" not in so_ambiguos


@pytest.mark.banco
def test_perfil_escrito_pela_ia_depois_de_aprender(cliente, empresa, sessao, ia_falsa):
    ia_falsa.respostas["perfil_empresa"] = {"perfil": "Creche que paga salários pela conta 187."}
    enviar(cliente, empresa)
    sessao.refresh(empresa)
    assert empresa.perfil_ia == "Creche que paga salários pela conta 187."
    pedido = ia_falsa.pedidos[-1][0]
    assert pedido.finalidade == "perfil_empresa" and "SINDICATO EXEMPLO" in pedido.pergunta


@pytest.mark.banco
def test_sem_ia_aprende_igual_e_sem_perfil(cliente, empresa, sessao):
    resposta = enviar(cliente, empresa)
    assert "Perfil da empresa não foi escrito" not in resposta.text  # sem chave: segue em silêncio
    sessao.refresh(empresa)
    assert empresa.perfil_ia is None


@pytest.mark.banco
@pytest.mark.parametrize(
    ("conteudo", "trecho"),
    [
        (LANCTOS.replace(b";230;", b";231;"), "é da empresa de código 231"),
        (b"Banco;Valor\nX;10\n", "Não reconheci o arquivo"),
        (LANCTOS + b"05/04/2026;99999;8;10;;FULANO - TESTE - S/N;1;230;;\r\n", None),
    ],
)
def test_arquivos_com_problema(cliente, empresa, sessao, conteudo, trecho):
    resposta = enviar(cliente, empresa, conteudo)
    if trecho:
        assert trecho in resposta.text
        assert sessao.scalar(select(LancamentoHistorico)) is None
    else:
        assert "1 linha(s) com conta que não existe no plano ficaram de fora" in resposta.text


@pytest.mark.banco
def test_historico_da_filial_usa_o_codigo_da_filial(cliente, empresa, sessao):
    empresa.codigo_filial = 231  # o lanctos.txt da filial traz 231 na coluna 8
    sessao.commit()
    assert "e esta usa o código 231" in enviar(cliente, empresa).text  # o arquivo da matriz (230) é recusado
    assert sessao.scalar(select(LancamentoHistorico)) is None
    enviar(cliente, empresa, LANCTOS.replace(b";230;", b";231;"))
    assert sessao.scalar(select(LancamentoHistorico)) is not None


@pytest.mark.banco
def test_sem_plano_pede_o_plano_antes(sessao):
    vazia = Empresa(codigo_dominio=500)
    sessao.add(vazia)
    sessao.commit()
    with pytest.raises(ErroLeitura, match="Importe o plano de contas"):
        importar_historico(sessao, vazia, "lanctos.txt", LANCTOS, None)


@pytest.mark.banco
@pytest.mark.amostras
def test_casa_crianca_real_2025_e_2026(sessao):
    """Os dois lanctos.txt reais do escritório com o plano real (AMOSTRAS)."""
    plano = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    arquivos = [AMOSTRAS / "historicos" / "lanctos_2025_casa_crianca.txt"]
    arquivos.append(AMOSTRAS / "PLANILHA EXPORTAÇÃO" / "modelo exemplar da exportacao.txt")
    if not plano.exists() or not all(a.exists() for a in arquivos):
        pytest.skip("AMOSTRAS/ não está neste computador")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(plano.read_bytes(), plano.name), None)
    for arquivo in arquivos:
        importar_historico(sessao, empresa, arquivo.name, arquivo.read_bytes(), None)
    resultado = aprender(sessao, empresa)
    sessao.commit()
    print("\n" + resultado.resumo().replace("🤖 ", ""))  # sem emoji: o terminal do Windows não mostra

    daniela = padrao(sessao, "FORNECEDOR", "DANIELA CORDEIRO OLIVEIRA")
    assert daniela.conta.reduzido == 187 and not daniela.ambiguo  # 2025 na 331, 2026 na 187
    siemaco = padrao(sessao, "FORNECEDOR", "SIEMACO")
    assert siemaco.detalhes["por_natureza"]["PLANO ODONTOLOGICO"]["conta"] == 10594
    assert siemaco.detalhes["por_natureza"]["CONTRIBUICAO NEGOCIAL"]["conta"] == 10595
    banco = sessao.scalar(select(ContaChave).where(ContaChave.tipo == "BANCO"))
    assert (banco.referencia, banco.conta.reduzido) == ("BB conta 72637-0", 8)  # critério da Fase 1
    assert resultado.ambiguos <= resultado.fornecedores * 0.15  # poucos para o usuário decidir


def test_natureza_exibida_sem_mes():
    from app.servicos.aprendizado import natureza_para_exibir

    assert natureza_para_exibir("SERVIÇOS CONTABEIS (JUNHO)") == "SERVIÇOS CONTABEIS"
    assert natureza_para_exibir("SALÁRIO MENSAL REF JANEIRO") == "SALÁRIO MENSAL"
    assert natureza_para_exibir("MAT. DE LIMPEZA (CLORO)") == "MAT. DE LIMPEZA (CLORO)"  # produto fica


@pytest.mark.banco
def test_padrao_que_o_historico_nao_sustenta_mais_sai_mas_o_do_usuario_fica(empresa, sessao):
    importar_historico(sessao, empresa, "lanctos.txt", LANCTOS, None)
    sessao.add_all(
        [
            Padrao(empresa_id=empresa.id, tipo="FORNECEDOR", chave="FANTASMA", nome="FANTASMA", origem="APRENDIDO"),
            Padrao(empresa_id=empresa.id, tipo="PALAVRA", chave="MINHA REGRA", nome="MINHA REGRA", origem="USUARIO"),
        ]
    )
    sessao.commit()
    aprender(sessao, empresa)
    sessao.commit()
    assert padrao(sessao, "FORNECEDOR", "FANTASMA") is None
    assert padrao(sessao, "PALAVRA", "MINHA REGRA") is not None
