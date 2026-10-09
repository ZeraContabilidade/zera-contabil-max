"""Preço por milhão de tokens, em dólares (tabela da Anthropic de 25/09/2026).

Serve para ESTIMAR o custo de cada chamada e respeitar o limite mensal do .env.
O valor oficial cobrado está em console.anthropic.com → Billing.
"""

from dataclasses import dataclass
from decimal import Decimal

UM_MILHAO = Decimal(1_000_000)


@dataclass(frozen=True)
class Preco:
    entrada: Decimal
    saida: Decimal
    cache_leitura: Decimal

    @property
    def cache_escrita(self) -> Decimal:
        return self.entrada * Decimal("1.25")  # gravar no cache de 5 minutos custa 25% a mais


PRECOS = {
    "claude-haiku-4-5": Preco(Decimal("1"), Decimal("5"), Decimal("0.10")),
    "claude-sonnet-5-5": Preco(Decimal("2"), Decimal("10"), Decimal("0.20")),
    "claude-opus-5-5": Preco(Decimal("4"), Decimal("20"), Decimal("0.20")),
    "claude-opus-4-8": Preco(Decimal("5"), Decimal("25"), Decimal("0.50")),  # recebe pedidos recusados
}
# modelo fora da tabela: estima pelo alto
_DESCONHECIDO = Preco(Decimal("10"), Decimal("50"), Decimal("1.00"))


def preco_do_modelo(modelo: str) -> Preco:
    """Aceita o nome com data que a API devolve (ex.: claude-haiku-4-5-20251001)."""
    for nome, preco in PRECOS.items():
        if modelo == nome or modelo.startswith(nome + "-"):
            return preco
    return _DESCONHECIDO


def estimar_custo(modelo: str, entrada: int, saida: int, cache_escrita: int = 0, cache_leitura: int = 0) -> Decimal:
    preco = preco_do_modelo(modelo)
    total = (
        entrada * preco.entrada
        + saida * preco.saida
        + cache_escrita * preco.cache_escrita
        + cache_leitura * preco.cache_leitura
    ) / UM_MILHAO
    return total.quantize(Decimal("0.000001"))
