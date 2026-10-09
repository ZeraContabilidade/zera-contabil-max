"""Competência (mês de trabalho) — sempre o 1º dia do mês."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)  # fmt: skip


def hoje() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def mes_anterior(referencia: date | None = None) -> date:
    """O escritório fecha o mês passado: é a competência padrão."""
    dia = referencia or hoje()
    return date(dia.year - 1, 12, 1) if dia.month == 1 else date(dia.year, dia.month - 1, 1)


def ler_competencia(texto: str | None) -> date | None:
    """'2026-09' (campo de mês do navegador) → date(2026, 9, 1)."""
    try:
        ano, mes = (int(parte) for parte in (texto or "").split("-"))
        return date(ano, mes, 1) if 2000 <= ano <= 2100 else None
    except ValueError:
        return None


def nome_competencia(competencia: date) -> str:
    return f"{MESES[competencia.month - 1]}/{competencia.year}"


def valor_campo_mes(competencia: date) -> str:
    return competencia.strftime("%Y-%m")
