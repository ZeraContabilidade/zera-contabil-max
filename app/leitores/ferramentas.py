"""Ajudantes comuns aos leitores de extrato: valores em reais e linhas de um PDF pela posição."""

import re
from decimal import Decimal
from typing import Any

DINHEIRO = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")  # 1.234,56
SALDO = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{0,2}$")  # 1.234,5 ou “0,” quando o PDF corta a coluna
DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def valor_br(texto: str) -> Decimal | None:
    """'1.234,56' → Decimal('1234.56')."""
    if not DINHEIRO.match(texto):
        return None
    return Decimal(texto.replace(".", "").replace(",", "."))


def saldo_br(texto: str) -> tuple[Decimal, bool] | None:
    """Saldo, que pode vir cortado pela impressão: '80.000,' → (80000, cortado=True)."""
    if not SALDO.match(texto):
        return None
    inteiro, centavos = texto.replace(".", "").split(",")
    cortado = len(centavos) < 2
    return Decimal(f"{inteiro}.{centavos.ljust(2, '0')}"), cortado


def linhas(palavras: list[dict[str, Any]], tolerancia: float = 3) -> list[list[dict[str, Any]]]:
    """Agrupa as palavras de uma página em linhas (mesma altura), cada linha da esquerda para a direita."""
    resultado: list[list[dict[str, Any]]] = []
    for palavra in sorted(palavras, key=lambda p: (round(p["top"]), p["x0"])):
        if resultado and abs(resultado[-1][0]["top"] - palavra["top"]) <= tolerancia:
            resultado[-1].append(palavra)
        else:
            resultado.append([palavra])
    return [sorted(linha, key=lambda p: p["x0"]) for linha in resultado]


def texto_da_linha(linha: list[dict[str, Any]]) -> str:
    return " ".join(p["text"] for p in linha)
