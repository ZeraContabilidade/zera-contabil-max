from app.modelos import Regime
from app.servicos.cnpj_publico import consultar_cnpj, regime_pelos_dados

# resposta no formato da BrasilAPI (anonimizada)
RESPOSTA_ASSOCIACAO = {
    "cnpj": "06101084000136",
    "razao_social": "ASSOCIACAO EXEMPLO DE CRECHES",
    "nome_fantasia": "",
    "codigo_natureza_juridica": 3999,
    "natureza_juridica": "Associação Privada",
    "cnae_fiscal_descricao": "Educação infantil - creche",
    "municipio": "ITAQUAQUECETUBA",
    "uf": "SP",
    "descricao_situacao_cadastral": "ATIVA",
    "opcao_pelo_simples": None,
    "opcao_pelo_mei": None,
}


def test_regime_descoberto_pelos_dados_publicos():
    assert regime_pelos_dados({"opcao_pelo_mei": True, "opcao_pelo_simples": True}) == Regime.MEI
    assert regime_pelos_dados({"opcao_pelo_simples": True}) == Regime.SIMPLES
    anos = [
        {"ano": 2023, "forma_de_tributacao": "LUCRO REAL"},
        {"ano": 2024, "forma_de_tributacao": "LUCRO PRESUMIDO"},
    ]
    assert regime_pelos_dados({"regime_tributario": anos}) == Regime.PRESUMIDO  # vale o ano mais recente
    assert regime_pelos_dados({"codigo_natureza_juridica": 3999}) == Regime.TERCEIRO_SETOR
    assert regime_pelos_dados({"codigo_natureza_juridica": 2062}) is None  # Ltda sem dado de regime


def test_consulta_monta_resumo(cnpj_responde):
    consultados = cnpj_responde(RESPOSTA_ASSOCIACAO)
    dados = consultar_cnpj("06101084000136")
    assert consultados == ["06101084000136"]
    assert dados.razao_social == "ASSOCIACAO EXEMPLO DE CRECHES"
    assert dados.nome_fantasia is None
    assert dados.regime == Regime.TERCEIRO_SETOR
    assert dados.resumo["natureza_juridica"] == "3999 - Associação Privada"
    assert dados.resumo["municipio"] == "ITAQUAQUECETUBA/SP"


def test_sem_internet_devolve_none():
    assert consultar_cnpj("06101084000136") is None  # o conftest simula "fora do ar"
