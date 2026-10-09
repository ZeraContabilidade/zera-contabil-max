"""Auto-configuração das contas-chave: regras, IA (cliente falso), conferência e escolha do usuário."""

import pytest
from sqlalchemy import select

from app.ia.cliente import ErroIA
from app.modelos import ContaChave, Empresa
from app.servicos.contas_chave import (
    auto_configurar,
    identificar_banco,
    ligar_conta_bancaria,
    natureza_do_grupo,
)
from app.servicos.plano import importar_plano, ler_plano
from tests.conftest import AMOSTRAS, entrar
from tests.planos import criar_plano


@pytest.fixture
def empresa(sessao):
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    return nova


def por_tipo(resultado):
    return {c.tipo: c for c in resultado.chaves}


@pytest.mark.parametrize(
    ("descricao", "natureza"),
    [
        ("CONTAS DE RESULTADOS - CUSTOS E DESPESAS", "DESPESA"),
        ("CONTAS DE RESULTADO - RECEITAS", "RECEITA"),
        ("RECEITAS", "RECEITA"),
        ("ATIVO", "ATIVO"),
        ("COMPENSAÇÃO ATIVA", "OUTRA"),
        ("CONTAS DE APURAÇÃO", "OUTRA"),
    ],
)
def test_natureza_pelo_nome_do_grupo_e_nao_pelo_numero(descricao, natureza):
    assert natureza_do_grupo(descricao) == natureza


def test_identificar_banco():
    assert identificar_banco("BB")[0] == "001"
    assert identificar_banco("Banco do Brasil S.A.")[0] == "001"
    assert identificar_banco("341")[1] == "ITAU"
    assert identificar_banco("Caixa Econômica Federal")[1] == "CEF"
    assert identificar_banco("CAIXA GERAL") is None  # caixa da empresa não é banco


@pytest.mark.banco
def test_regras_acham_sozinhas_e_sem_ia_o_resto_fica_para_conferir(sessao, empresa):
    resultado = auto_configurar(sessao, empresa)
    chaves = por_tipo(resultado)
    for tipo, reduzido in {
        "IR_RETIDO": 31,
        "SALARIOS": 187,
        "FGTS": 192,
        "INSS": 191,
        "FORNECEDOR_GENERICO": 10001,
        "JUROS_PAGOS": 368,
    }.items():
        assert chaves[tipo].conta.reduzido == reduzido, tipo
        assert chaves[tipo].origem == "REGRA" and chaves[tipo].confianca >= 85
    # várias parecidas e IA desligada: a primeira do plano, para conferir
    assert chaves["TARIFA"].conta.reduzido == 535 and chaves["TARIFA"].confianca == 60
    assert "Confira" in chaves["TARIFA"].justificativa
    assert chaves["RENDIMENTO"].conta.reduzido == 432
    assert chaves["IOF"].conta is None  # não existe no plano
    assert "CONFIGURAR_IA.bat" in resultado.aviso_ia
    assert resultado.resumo() == "🤖 Contas-chave: 6 achadas, 2 para conferir, 2 não encontrada(s)."
    # conta individual por fornecedor descoberta pelo grupo 2.1.3.01
    assert empresa.usa_conta_individual is True and empresa.grupo_fornecedores == "2.1.3.01"
    assert empresa.e_automatico("usa_conta_individual")


@pytest.mark.banco
def test_ia_resolve_so_as_incertas_e_e_conferida(sessao, empresa, ia_falsa):
    ia_falsa.respostas["auto_configuracao"] = {
        "contas": [
            {"tipo": "TARIFA", "conta_reduzida": 535, "confianca": 92, "justificativa": "535 é a geral."},
            {"tipo": "RENDIMENTO", "conta_reduzida": 10107, "confianca": 70, "justificativa": "Provável."},
            {"tipo": "IOF", "conta_reduzida": 0, "confianca": 0, "justificativa": "Não há conta de IOF."},
            {"tipo": "CLIENTE_GENERICO", "conta_reduzida": 187, "confianca": 95, "justificativa": "x"},
        ]
    }
    chaves = por_tipo(auto_configurar(sessao, empresa))

    pedido, modelo = ia_falsa.pedidos[0]
    assert modelo == "claude-sonnet-5-5" and pedido.forte
    assert "535 | 3.2.2.05.000011 | TARIFA BANCÁRIA | analítica | DESPESA" in pedido.contexto
    assert "tipo TARIFA" in pedido.pergunta and "tipo SALARIOS" not in pedido.pergunta  # só as incertas

    assert chaves["TARIFA"].conta.reduzido == 535 and chaves["TARIFA"].origem == "IA"
    assert chaves["RENDIMENTO"].conta.reduzido == 10107 and chaves["RENDIMENTO"].confianca == 70
    assert chaves["IOF"].conta is None
    # 187 é do PASSIVO e cliente precisa ser do ATIVO: a sugestão da IA é recusada
    assert chaves["CLIENTE_GENERICO"].conta is None
    assert "não aplicada" in chaves["CLIENTE_GENERICO"].justificativa
    assert chaves["SALARIOS"].origem == "REGRA"


@pytest.mark.banco
def test_ia_nao_inventa_conta_nem_usa_grupo(sessao, empresa, ia_falsa):
    ia_falsa.respostas["auto_configuracao"] = {
        "contas": [
            {"tipo": "TARIFA", "conta_reduzida": 99999, "confianca": 99, "justificativa": "inventada"},
            {"tipo": "JUROS_PAGOS", "conta_reduzida": 367, "confianca": 99, "justificativa": "grupo"},
            {"tipo": "RENDIMENTO", "conta_reduzida": 432, "confianca": 30, "justificativa": "palpite"},
        ]
    }
    chaves = por_tipo(auto_configurar(sessao, empresa))
    assert chaves["TARIFA"].conta is None and "não existe como analítica" in chaves["TARIFA"].justificativa
    assert chaves["RENDIMENTO"].conta is None and "Palpite fraco" in chaves["RENDIMENTO"].justificativa


@pytest.mark.banco
def test_ia_fora_do_ar_usa_as_regras_e_avisa(sessao, empresa, ia_falsa):
    ia_falsa.respostas["auto_configuracao"] = ErroIA("A IA da Anthropic está fora do ar.")
    resultado = auto_configurar(sessao, empresa)
    assert por_tipo(resultado)["TARIFA"].conta.reduzido == 535
    assert "fora do ar" in resultado.aviso_ia


@pytest.mark.banco
@pytest.mark.parametrize(
    ("nome_banco", "numero", "tipo", "reduzido"),
    [
        ("BB", "12345-6", "BANCO", 8),
        ("Banco do Brasil", "12345-6", "POUPANCA", 11),
        ("341", "5555-1", "BANCO", 9),
    ],
)
def test_conta_bancaria_do_extrato_vai_para_a_conta_certa(sessao, empresa, nome_banco, numero, tipo, reduzido):
    chave, _ = ligar_conta_bancaria(sessao, empresa, nome_banco, "2180-6", numero, tipo)
    assert chave.conta.reduzido == reduzido and chave.origem == "REGRA" and chave.confianca >= 80


@pytest.mark.banco
def test_conta_bancaria_sem_conta_no_plano_gera_aviso(sessao, empresa):
    chave, aviso_ia = ligar_conta_bancaria(sessao, empresa, "BB", "2180-6", "99999-9", "POUPANCA")
    assert chave.conta is None
    assert "Não encontrei no plano uma conta para a poupança do Banco do Brasil ag. 2180-6 conta 99999-9" in (
        chave.justificativa
    )
    assert "crie no Domínio e reimporte o plano" in chave.justificativa
    assert chave.referencia == "BB conta 99999-9"
    assert aviso_ia  # IA desligada nos testes


@pytest.mark.banco
def test_tela_mostra_troca_e_escolha_do_usuario_nao_e_sobrescrita(cliente, criar_usuario, sessao, empresa):
    criar_usuario("ana")
    entrar(cliente, "ana")
    cliente.post(f"/empresas/{empresa.id}/contas-chave/refazer")
    html = cliente.get(f"/empresas/{empresa.id}", params={"aba": "plano"}).text
    assert "Contas-chave" in html and "Tarifas bancárias" in html and "⚠ não encontrada" in html
    assert 'option value="535 – TARIFA BANCÁRIA"' in html  # autocompletar só com analíticas
    assert 'option value="367 – DESPESAS FINANCEIRAS"' not in html
    assert "conta individual por fornecedor (grupo 2.1.3.01)" in html

    tarifa = sessao.scalar(select(ContaChave).where(ContaChave.tipo == "TARIFA"))
    erro = cliente.post(
        f"/empresas/{empresa.id}/contas-chave/{tarifa.id}", data={"conta": "367"}, follow_redirects=True
    )
    assert "é sintética (grupo)" in erro.text
    resposta = cliente.post(
        f"/empresas/{empresa.id}/contas-chave/{tarifa.id}",
        data={"conta": "10162 – TARIFAS BANCARIAS"},
        follow_redirects=True,
    )
    assert "Tarifas bancárias: agora usa 10162 – TARIFAS BANCARIAS." in resposta.text

    cliente.post(f"/empresas/{empresa.id}/contas-chave/refazer")  # refazer não desfaz a escolha
    sessao.expire_all()
    tarifa = sessao.get(ContaChave, tarifa.id)
    assert (tarifa.conta.reduzido, tarifa.origem) == (10162, "USUARIO")


@pytest.mark.banco
def test_importar_plano_ja_configura_sozinho(cliente, criar_usuario, sessao):
    from tests.conftest import DADOS

    criar_usuario("ana")
    entrar(cliente, "ana")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    resposta = cliente.post(
        f"/empresas/{empresa.id}/plano",
        files={"arquivo": ("plano.txt", (DADOS / "plano_exemplo.txt").read_bytes())},
        follow_redirects=True,
    )
    assert "🤖 Contas-chave:" in resposta.text
    assert sessao.scalar(select(ContaChave).where(ContaChave.tipo == "SALARIOS")).conta.reduzido == 187


@pytest.mark.banco
@pytest.mark.amostras
def test_casa_crianca_real_sem_ia(sessao):
    """Plano real (AMOSTRAS): as regras acertam o que o lanctos.txt do escritório usa."""
    arquivo = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    if not arquivo.exists():
        pytest.skip("AMOSTRAS/ não está neste computador")
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(arquivo.read_bytes(), arquivo.name), None)
    sessao.commit()

    chaves = por_tipo(auto_configurar(sessao, empresa))
    assert {t: chaves[t].conta.reduzido for t in ("SALARIOS", "FGTS", "INSS", "IR_RETIDO")} == {
        "SALARIOS": 187,
        "FGTS": 192,
        "INSS": 191,
        "IR_RETIDO": 31,
    }
    assert (empresa.usa_conta_individual, empresa.grupo_fornecedores) == (True, "2.1.3.01")

    corrente, _ = ligar_conta_bancaria(sessao, empresa, "BB", "2180-6", "72637-0", "BANCO")
    assert corrente.conta.reduzido == 8  # exemplo da especificação (§3.2.1)
    poupanca, _ = ligar_conta_bancaria(sessao, empresa, "BB", "2180-6", "72637-0", "POUPANCA")
    assert poupanca.conta is None  # o plano não tem conta da poupança: vira aviso
