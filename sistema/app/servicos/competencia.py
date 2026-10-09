"""Competência (mês de trabalho) — sempre o 1º dia do mês — e período de trabalho (de um mês até outro)."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)  # fmt: skip
MAXIMO_MESES = 24  # um período maior que dois anos deixaria a Revisão pesada demais
SEPARADOR_PERIODO = "_"  # “2025-01_2025-12” nos endereços das telas


def hoje() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def mes_anterior(referencia: date | None = None) -> date:
    """O escritório fecha o mês passado: é a competência padrão."""
    dia = referencia or hoje()
    return date(dia.year - 1, 12, 1) if dia.month == 1 else date(dia.year, dia.month - 1, 1)


def somar_meses(mes: date, quantos: int) -> date:
    total = mes.year * 12 + mes.month - 1 + quantos
    return date(total // 12, total % 12 + 1, 1)


@dataclass(frozen=True)
class Periodo:
    """Do 1º dia do mês `inicio` ao último dia do mês `fim`. Um mês só = `inicio == fim` (o caso de sempre)."""

    inicio: date
    fim: date

    @classmethod
    def do_mes(cls, mes: date) -> "Periodo":
        return cls(mes, mes)

    @classmethod
    def entre(cls, de: date, ate: date) -> "Periodo":
        """Põe na ordem e corta em MAXIMO_MESES (a partir do primeiro mês)."""
        de, ate = sorted((de.replace(day=1), ate.replace(day=1)))
        return cls(de, min(ate, somar_meses(de, MAXIMO_MESES - 1)))

    @property
    def um_mes(self) -> bool:
        return self.inicio == self.fim

    @property
    def ultimo_dia(self) -> date:
        return date(self.fim.year, self.fim.month, calendar.monthrange(self.fim.year, self.fim.month)[1])

    @property
    def limites(self) -> tuple[date, date]:
        return self.inicio, self.ultimo_dia

    @property
    def meses(self) -> list[date]:
        quantos = (self.fim.year - self.inicio.year) * 12 + self.fim.month - self.inicio.month + 1
        return [somar_meses(self.inicio, n) for n in range(quantos)]

    def contem(self, dia: date) -> bool:
        return self.inicio <= dia <= self.ultimo_dia


def como_periodo(competencia: "date | Periodo") -> Periodo:
    """As regras aceitam um mês (date) ou um período: o mês vira um período de um mês só."""
    return competencia if isinstance(competencia, Periodo) else Periodo.do_mes(competencia.replace(day=1))


def ler_competencia(texto: str | None) -> date | None:
    """'2026-09' (campo de mês do navegador) → date(2026, 9, 1)."""
    try:
        ano, mes = (int(parte) for parte in (texto or "").split("-"))
        return date(ano, mes, 1) if 2000 <= ano <= 2100 else None
    except ValueError:
        return None


def ler_periodo(texto: str | None, ate: str | None = None) -> Periodo | None:
    """'2026-09' → um mês; '2025-01_2025-12' (endereço) ou texto='2025-01' + ate='2025-12' (tela) → período."""
    partes = (texto or "").split(SEPARADOR_PERIODO)
    if ate:
        partes = [partes[0], ate]
    meses = [ler_competencia(parte) for parte in partes]
    if not 1 <= len(meses) <= 2 or None in meses:
        return None
    return Periodo.entre(meses[0], meses[-1])


def nome_competencia(competencia: "date | Periodo") -> str:
    """“agosto/2026” ou, num período, “janeiro/2025 a dezembro/2025”."""
    periodo = como_periodo(competencia)
    nome = f"{MESES[periodo.inicio.month - 1]}/{periodo.inicio.year}"
    return nome if periodo.um_mes else f"{nome} a {MESES[periodo.fim.month - 1]}/{periodo.fim.year}"


def valor_campo_mes(competencia: "date | Periodo") -> str:
    """O valor que vai nos endereços e formulários: “2026-08” ou “2025-01_2025-12”."""
    periodo = como_periodo(competencia)
    valor = periodo.inicio.strftime("%Y-%m")
    return valor if periodo.um_mes else f"{valor}{SEPARADOR_PERIODO}{periodo.fim:%Y-%m}"


def periodo_no_arquivo(competencia: "date | Periodo") -> str:
    """No nome dos arquivos baixados: “2026-08” ou “2025-01_a_2025-12”."""
    periodo = como_periodo(competencia)
    return f"{periodo.inicio:%Y-%m}" if periodo.um_mes else f"{periodo.inicio:%Y-%m}_a_{periodo.fim:%Y-%m}"
