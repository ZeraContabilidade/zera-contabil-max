"""Conversa com a API da Anthropic. O resto do sistema só enxerga PedidoIA → RespostaIA.

- Resposta sempre em JSON válido: saída estruturada (`output_config.format` com JSON Schema).
- Contexto grande e estável (plano de contas, perfil da empresa) vai marcado para o cache de prompt,
  que barateia os lotes seguintes.
- Modelos que aceitam (Sonnet 5.5): se a IA recusar por segurança, a própria API repete o pedido
  num modelo substituto (`fallbacks: "default"`).
- Endereço da API fixo (config `ia_endereco`): uma ANTHROPIC_BASE_URL de outro programa
  não desvia as chamadas.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

MODELOS_COM_SUBSTITUTO = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")
MODELOS_SEM_ESFORCO = ("claude-haiku-4-5",)  # o Haiku 4.5 não aceita o parâmetro effort
BETA_SUBSTITUTO = "server-side-fallback-2026-07-01"


@dataclass
class UsoTokens:
    entrada: int = 0
    saida: int = 0
    cache_escrita: int = 0
    cache_leitura: int = 0


class ErroIA(Exception):
    """A IA não ajudou neste pedido; a mensagem diz o que fazer. Quem chamou segue sem a IA."""

    def __init__(self, mensagem: str, uso: UsoTokens | None = None, modelo: str | None = None):
        super().__init__(mensagem)
        self.uso = uso
        self.modelo = modelo


@dataclass
class PedidoIA:
    finalidade: str  # ex.: auto_configuracao, classificacao, leitura_pdf, teste
    instrucoes: str  # o que a IA deve fazer — fixo para cada finalidade
    pergunta: str  # os dados deste pedido
    esquema: dict[str, Any]  # JSON Schema da resposta (additionalProperties: false)
    contexto: str = ""  # bloco grande e estável (plano de contas, perfil): vai para o cache
    forte: bool = False  # True = modelo forte (IA_MODELO_FORTE)
    esforco: str | None = None  # "low", "medium"... (ignorado no Haiku)
    max_tokens: int = 16000


@dataclass
class RespostaIA:
    dados: dict[str, Any]
    modelo: str
    uso: UsoTokens = field(default_factory=UsoTokens)
    request_id: str | None = None


class ClienteIA(Protocol):
    def gerar(self, pedido: PedidoIA, modelo: str) -> RespostaIA: ...


def mensagem_de_erro(erro: anthropic.APIError) -> str:
    """Erros da API → o que o usuário deve fazer. Do mais específico para o mais geral."""
    if isinstance(erro, anthropic.AuthenticationError):
        return (
            "A chave da API da Anthropic foi recusada. Rode o Ferramentas\\CONFIGURAR_IA.bat, cole a chave de novo "
            "e abra o sistema de novo."
        )
    if isinstance(erro, anthropic.PermissionDeniedError):
        return "A chave da API não tem permissão para usar este modelo. Confira a conta em console.anthropic.com."
    if isinstance(erro, anthropic.NotFoundError):
        return "O modelo de IA configurado não foi encontrado. Confira IA_MODELO_RAPIDO e IA_MODELO_FORTE no .env."
    if isinstance(erro, anthropic.RateLimitError):
        return "Muitas chamadas à IA em pouco tempo. Aguarde alguns minutos e tente de novo."
    if isinstance(erro, anthropic.BadRequestError):
        if "credit balance" in str(erro.message).lower():
            return "Os créditos da conta da Anthropic acabaram. Compre créditos em console.anthropic.com → Billing."
        return f"A API da Anthropic recusou o pedido: {erro.message}"
    if isinstance(erro, anthropic.APIStatusError):
        return (
            "A IA da Anthropic está fora do ar ou sobrecarregada agora. Nada se perde: "
            "o sistema segue só com regras e aprendizado, e dá para tentar de novo mais tarde."
        )
    if isinstance(erro, anthropic.APITimeoutError):
        return "A IA demorou demais para responder. Tente de novo em instantes."
    if isinstance(erro, anthropic.APIConnectionError):
        return "Sem conexão com a IA (confira a internet). O sistema segue só com regras e aprendizado."
    return f"Erro ao falar com a IA: {erro}"


def _uso(resposta: Any) -> UsoTokens:
    uso = resposta.usage
    return UsoTokens(
        entrada=uso.input_tokens or 0,
        saida=uso.output_tokens or 0,
        cache_escrita=getattr(uso, "cache_creation_input_tokens", 0) or 0,
        cache_leitura=getattr(uso, "cache_read_input_tokens", 0) or 0,
    )


def ler_resposta(resposta: Any) -> RespostaIA:
    uso, modelo = _uso(resposta), resposta.model
    if resposta.stop_reason == "refusal":
        raise ErroIA(
            "A IA se recusou a responder este pedido (filtro de segurança da Anthropic). Fica para conferência manual.",
            uso,
            modelo,
        )
    if resposta.stop_reason == "max_tokens":
        raise ErroIA(
            "A resposta da IA passou do tamanho máximo e foi cortada. Tente com menos linhas por vez.",
            uso,
            modelo,
        )
    texto = next((bloco.text for bloco in resposta.content if bloco.type == "text"), None)
    try:
        dados = json.loads(texto) if texto else None
    except json.JSONDecodeError:
        dados = None
    if not isinstance(dados, dict):
        raise ErroIA("A IA devolveu uma resposta fora do formato combinado.", uso, modelo)
    return RespostaIA(dados, modelo, uso, getattr(resposta, "_request_id", None))


class ClienteAnthropic:
    def __init__(self, chave: str, endereco: str, sdk: Any = None):
        self.sdk = sdk or anthropic.Anthropic(api_key=chave, base_url=endereco, timeout=120.0, max_retries=2)

    def gerar(self, pedido: PedidoIA, modelo: str) -> RespostaIA:
        sistema = [{"type": "text", "text": pedido.instrucoes}]
        if pedido.contexto:
            sistema.append({"type": "text", "text": pedido.contexto})
        sistema[-1]["cache_control"] = {"type": "ephemeral"}  # instruções + contexto estáveis → cache

        saida: dict[str, Any] = {"format": {"type": "json_schema", "schema": pedido.esquema}}
        if pedido.esforco and not modelo.startswith(MODELOS_SEM_ESFORCO):
            saida["effort"] = pedido.esforco
        argumentos = {
            "model": modelo,
            "max_tokens": pedido.max_tokens,
            "system": sistema,
            "messages": [{"role": "user", "content": pedido.pergunta}],
            "output_config": saida,
        }
        try:
            if modelo.startswith(MODELOS_COM_SUBSTITUTO):
                resposta = self.sdk.beta.messages.create(betas=[BETA_SUBSTITUTO], fallbacks="default", **argumentos)
            else:
                resposta = self.sdk.messages.create(**argumentos)
        except anthropic.APIError as erro:
            raise ErroIA(mensagem_de_erro(erro), modelo=modelo) from erro
        return ler_resposta(resposta)


class ClienteFalso:
    """Respostas gravadas, para testes e para o modo de demonstração (IA_SIMULADA=true).
    `respostas`: {finalidade: dados} ou uma função (pedido) → dados. Um Exception na resposta é lançado."""

    def __init__(
        self,
        respostas: dict[str, Any] | Callable[[PedidoIA], Any] | None = None,
        uso: UsoTokens | None = None,
    ):
        self.respostas = respostas or {}
        self.uso = uso or UsoTokens(entrada=1200, saida=150)
        self.pedidos: list[tuple[PedidoIA, str]] = []

    def gerar(self, pedido: PedidoIA, modelo: str) -> RespostaIA:
        self.pedidos.append((pedido, modelo))
        resposta = self.respostas(pedido) if callable(self.respostas) else self.respostas.get(pedido.finalidade)
        if isinstance(resposta, Exception):
            raise resposta
        if resposta is None:
            raise ErroIA(f"Sem resposta gravada para “{pedido.finalidade}” no modo simulado.", modelo=modelo)
        return RespostaIA(dados=resposta, modelo=modelo, uso=self.uso, request_id="simulado")


RESPOSTAS_DEMONSTRACAO: dict[str, Any] = {
    "teste": {"ok": True, "mensagem": "Olá! Esta é uma resposta simulada."},
    "perfil_empresa": {
        "perfil": "Perfil de demonstração (IA simulada): com a chave da API, a IA escreve aqui o resumo real."
    },
    "historico_ia": {"itens": []},  # no modo simulado a IA não muda o histórico
    "leitura_pdf": {"e_extrato": False},  # no modo simulado a IA não lê extratos
    "classificacao": {"itens": []},  # nem classifica
    "colunas_planilha": {"linha_titulos": -1},
}
