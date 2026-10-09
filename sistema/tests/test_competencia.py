from datetime import date

from app.servicos.competencia import (
    MAXIMO_MESES,
    Periodo,
    como_periodo,
    ler_competencia,
    ler_periodo,
    mes_anterior,
    nome_competencia,
    periodo_no_arquivo,
    valor_campo_mes,
)


def test_mes_padrao_e_o_mes_passado_inclusive_na_virada_do_ano():
    assert mes_anterior(date(2026, 10, 6)) == date(2026, 9, 1)
    assert mes_anterior(date(2027, 1, 15)) == date(2026, 12, 1)


def test_ler_e_mostrar_competencia():
    assert ler_competencia("2026-09") == date(2026, 9, 1)
    assert ler_competencia("lixo") is None
    assert ler_competencia("2026-13") is None
    assert ler_competencia(None) is None
    assert nome_competencia(date(2026, 3, 1)) == "março/2026"
    assert valor_campo_mes(date(2026, 3, 1)) == "2026-03"


ANO_2025 = Periodo(date(2025, 1, 1), date(2025, 12, 1))


def test_periodo_de_um_mes_ate_outro():
    assert ANO_2025.limites == (date(2025, 1, 1), date(2025, 12, 31))
    assert len(ANO_2025.meses) == 12 and ANO_2025.meses[-1] == date(2025, 12, 1)
    assert ANO_2025.contem(date(2025, 7, 15)) and not ANO_2025.contem(date(2026, 1, 1))
    assert not ANO_2025.um_mes and Periodo.do_mes(date(2026, 2, 1)).ultimo_dia == date(2026, 2, 28)
    assert como_periodo(date(2026, 8, 1)) == Periodo(date(2026, 8, 1), date(2026, 8, 1))


def test_ler_e_mostrar_periodo():
    assert ler_periodo("2025-01_2025-12") == ANO_2025  # vindo de um endereço
    assert ler_periodo("2025-01", "2025-12") == ANO_2025  # “De” e “Até” da tela
    assert ler_periodo("2025-12", "2025-01") == ANO_2025  # de trás para frente: põe na ordem
    assert ler_periodo("2026-08") == Periodo.do_mes(date(2026, 8, 1))
    assert ler_periodo("lixo") is None and ler_periodo("2025-01_lixo") is None and ler_periodo(None) is None
    longo = ler_periodo("2020-01", "2026-12")  # mais de dois anos: corta
    assert len(longo.meses) == MAXIMO_MESES and longo.inicio == date(2020, 1, 1)
    assert nome_competencia(ANO_2025) == "janeiro/2025 a dezembro/2025"
    assert nome_competencia(Periodo.do_mes(date(2026, 8, 1))) == "agosto/2026"
    assert valor_campo_mes(ANO_2025) == "2025-01_2025-12"
    assert valor_campo_mes(Periodo.do_mes(date(2026, 8, 1))) == "2026-08"
    assert periodo_no_arquivo(ANO_2025) == "2025-01_a_2025-12"
    assert periodo_no_arquivo(date(2026, 8, 1)) == "2026-08"
