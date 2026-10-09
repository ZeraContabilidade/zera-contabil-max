import pytest

from app.servicos.documentos import (
    cnpj_valido,
    cpf_valido,
    formatar_documento,
    normalizar_documento,
    tipo_documento,
)

CNPJ_CASA_CRIANCA = "06.101.084/0001-36"


def test_cnpj_da_casa_crianca_e_valido_com_ou_sem_pontuacao():
    assert cnpj_valido(CNPJ_CASA_CRIANCA)
    assert cnpj_valido("06101084000136")
    assert normalizar_documento(CNPJ_CASA_CRIANCA) == "06101084000136"


@pytest.mark.parametrize("errado", ["06.101.084/0001-37", "11.111.111/1111-11", "0610108400013", "", None])
def test_cnpj_invalido(errado):
    assert not cnpj_valido(errado)


def test_cnpj_alfanumerico_da_receita_julho_2026():
    # exemplo oficial da Receita/Serpro para o CNPJ com letras
    assert cnpj_valido("12.ABC.345/01DE-35")
    assert cnpj_valido("12abc34501de35")  # minúsculas também
    assert not cnpj_valido("12.ABC.345/01DE-36")
    assert formatar_documento("12abc34501de35") == "12.ABC.345/01DE-35"


def test_cnpj_do_historico_de_2025_com_digito_faltando_e_recusado():
    assert not cnpj_valido("31.599.393/000-25")


def test_cpf():
    assert cpf_valido("529.982.247-25")
    assert not cpf_valido("529.982.247-26")
    assert not cpf_valido("111.111.111-11")
    assert tipo_documento("52998224725") == "CPF"
    assert formatar_documento("52998224725") == "529.982.247-25"


def test_tipo_documento():
    assert tipo_documento(CNPJ_CASA_CRIANCA) == "CNPJ"
    assert tipo_documento("123") is None
