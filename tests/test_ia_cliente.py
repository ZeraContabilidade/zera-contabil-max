"""Cliente da API da Anthropic, testado com um SDK falso (sem internet e sem custo)."""

from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.ia.cliente import ClienteAnthropic, ErroIA, PedidoIA
from app.ia.precos import estimar_custo

ESQUEMA = {
    "type": "object",
    "properties": {"conta": {"type": "integer"}},
    "required": ["conta"],
    "additionalProperties": False,
}


def resposta_falsa(texto='{"conta": 355}', parada="end_turn", modelo="claude-haiku-4-5-20251001"):
    return SimpleNamespace(
        stop_reason=parada,
        model=modelo,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        usage=SimpleNamespace(
            input_tokens=900, output_tokens=40, cache_creation_input_tokens=5000, cache_read_input_tokens=0
        ),
        _request_id="req_teste",
    )


class SdkFalso:
    def __init__(self, resposta=None, erro=None):
        self.chamadas = []
        self._resposta, self._erro = resposta or resposta_falsa(), erro
        self.messages = SimpleNamespace(create=self._criar("normal"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._criar("beta")))

    def _criar(self, rota):
        def criar(**argumentos):
            self.chamadas.append((rota, argumentos))
            if self._erro:
                raise self._erro
            return self._resposta

        return criar


def pedido(**extra):
    return PedidoIA(
        finalidade="classificacao",
        instrucoes="Classifique.",
        pergunta="SABESP 120,00",
        esquema=ESQUEMA,
        contexto="PLANO DE CONTAS...",
        **extra,
    )


def test_pedido_rapido_vai_com_cache_e_json_garantido():
    sdk = SdkFalso()
    resposta = ClienteAnthropic("chave", "https://api.anthropic.com", sdk).gerar(pedido(), "claude-haiku-4-5")
    rota, argumentos = sdk.chamadas[0]
    assert rota == "normal"  # o Haiku não tem modelo substituto
    assert argumentos["system"][0] == {"type": "text", "text": "Classifique."}
    assert argumentos["system"][1]["cache_control"] == {"type": "ephemeral"}  # plano de contas no cache
    assert argumentos["output_config"] == {"format": {"type": "json_schema", "schema": ESQUEMA}}
    assert argumentos["messages"] == [{"role": "user", "content": "SABESP 120,00"}]
    assert resposta.dados == {"conta": 355}
    assert (resposta.uso.entrada, resposta.uso.saida, resposta.uso.cache_escrita) == (900, 40, 5000)
    assert resposta.request_id == "req_teste"


def test_modelo_forte_usa_esforco_e_substituto_em_caso_de_recusa():
    sdk = SdkFalso(resposta_falsa(modelo="claude-sonnet-5-5"))
    cliente = ClienteAnthropic("chave", "https://api.anthropic.com", sdk)
    cliente.gerar(pedido(forte=True, esforco="medium"), "claude-sonnet-5-5")
    rota, argumentos = sdk.chamadas[0]
    assert rota == "beta"
    assert argumentos["betas"] == ["server-side-fallback-2026-07-01"]
    assert argumentos["fallbacks"] == "default"
    assert argumentos["output_config"]["effort"] == "medium"


def test_haiku_nao_recebe_esforco():
    sdk = SdkFalso()
    ClienteAnthropic("chave", "x", sdk).gerar(pedido(esforco="low"), "claude-haiku-4-5")
    assert "effort" not in sdk.chamadas[0][1]["output_config"]


@pytest.mark.parametrize(
    ("resposta", "trecho"),
    [
        (resposta_falsa(parada="refusal"), "se recusou"),
        (resposta_falsa(parada="max_tokens"), "foi cortada"),
        (resposta_falsa(texto="não é json"), "fora do formato"),
        (resposta_falsa(texto="[1, 2]"), "fora do formato"),
    ],
)
def test_resposta_ruim_vira_erro_explicado_com_os_tokens_gastos(resposta, trecho):
    with pytest.raises(ErroIA, match=trecho) as erro:
        ClienteAnthropic("chave", "x", SdkFalso(resposta)).gerar(pedido(), "claude-haiku-4-5")
    assert erro.value.uso.entrada == 900  # tokens cobrados mesmo sem resposta útil


def _erro_http(classe, status, mensagem="erro"):
    pedido_http = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return classe(mensagem, response=httpx2.Response(status, request=pedido_http), body=None)


@pytest.mark.parametrize(
    ("erro", "trecho"),
    [
        (_erro_http(anthropic.AuthenticationError, 401), "chave da API da Anthropic foi recusada"),
        (_erro_http(anthropic.BadRequestError, 400, "Your credit balance is too low"), "créditos"),
        (_erro_http(anthropic.RateLimitError, 429), "Muitas chamadas"),
        (_erro_http(anthropic.InternalServerError, 529), "fora do ar ou sobrecarregada"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "confira a internet"),
    ],
)
def test_erros_da_api_dizem_o_que_fazer(erro, trecho):
    with pytest.raises(ErroIA, match=trecho):
        ClienteAnthropic("chave", "x", SdkFalso(erro=erro)).gerar(pedido(), "claude-haiku-4-5")


def test_endereco_da_api_fixo_mesmo_com_variavel_de_outro_programa(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9999/desvio")
    cliente = ClienteAnthropic("chave-falsa", "https://api.anthropic.com")
    assert str(cliente.sdk.base_url).startswith("https://api.anthropic.com")


def test_custo_estimado_em_dolares():
    # Haiku 4.5: US$ 1 entrada, 5 saída, cache 1,25 escrita / 0,10 leitura por milhão
    assert estimar_custo("claude-haiku-4-5-20251001", 900, 40, 5000, 0) == Decimal("0.007350")
    # Sonnet 5.5: US$ 2 entrada, 10 saída, 0,20 leitura de cache
    assert estimar_custo("claude-sonnet-5-5", 1_000_000, 0, 0, 1_000_000) == Decimal("2.200000")
    # modelo fora da tabela: estima pelo alto
    assert estimar_custo("modelo-novo", 1_000_000, 0) == Decimal("10.000000")
