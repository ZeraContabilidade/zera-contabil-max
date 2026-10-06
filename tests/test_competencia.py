from datetime import date

from app.servicos.competencia import ler_competencia, mes_anterior, nome_competencia, valor_campo_mes


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
