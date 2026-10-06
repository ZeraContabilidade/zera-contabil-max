from app.servicos.complemento import EXEMPLO, MODELO_PADRAO, montar_complemento, problema_no_modelo


def test_modelo_padrao_igual_ao_lanctos_do_escritorio():
    assert montar_complemento(MODELO_PADRAO, EXEMPLO) == "SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N"


def test_parte_vazia_some_com_o_separador():
    valores = {"FAVORECIDO": "ALINE NILLIO DE SOUZA", "NATUREZA": "RESCISÃO", "DOCUMENTO": "S/N"}
    assert montar_complemento(MODELO_PADRAO, valores) == "ALINE NILLIO DE SOUZA - RESCISÃO - S/N"
    assert montar_complemento(MODELO_PADRAO, {"NATUREZA": "TARIFA"}) == "TARIFA"
    assert montar_complemento(MODELO_PADRAO, {}) == ""
    assert montar_complemento("TEXTO SOLTO", EXEMPLO) == ""  # modelo sem partes não quebra a tela


def test_ponto_e_virgula_e_espacos_extras_nao_quebram_o_txt():
    valores = {"FAVORECIDO": "LOJA;  X", "NATUREZA": "CESTA BASICA "}
    assert montar_complemento(MODELO_PADRAO, valores) == "LOJA, X - CESTA BASICA"


def test_modelo_personalizado():
    valores = {"FAVORECIDO": "SABESP", "NATUREZA": "AGUA", "DOCUMENTO": "123"}
    assert (
        montar_complemento("PAGTO NATUREZA / FAVORECIDO (DOCUMENTO)", valores) == "PAGTO AGUA / SABESP (123)"
    )


def test_problemas_no_modelo_explicam_o_que_fazer():
    assert problema_no_modelo(MODELO_PADRAO) is None
    assert "ponto e vírgula" in problema_no_modelo("FAVORECIDO; NATUREZA")
    assert "FAVORECIDO" in problema_no_modelo("PAGAMENTO")
    assert "Preencha" in problema_no_modelo("  ")
