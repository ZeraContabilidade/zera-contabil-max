"""Complemento do histórico do lançamento, montado a partir do modelo da empresa.

Modelo padrão: "FAVORECIDO - CNPJ - NATUREZA - DOCUMENTO"
→ "SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N"
Parte sem valor some junto com o separador (sem CNPJ: "ALINE DE SOUZA - RESCISÃO - S/N").
"""

import re

PARTES = ("FAVORECIDO", "CNPJ", "NATUREZA", "DOCUMENTO")
MODELO_PADRAO = "FAVORECIDO - CNPJ - NATUREZA - DOCUMENTO"
EXEMPLO = {
    "FAVORECIDO": "SABESP",
    "CNPJ": "43.776.517/0001-80",
    "NATUREZA": "CONTA DE AGUA",
    "DOCUMENTO": "S/N",
}
_DIVIDIR = re.compile(r"(" + "|".join(PARTES) + r")")
_ESPACOS = re.compile(r"\s+")


def problema_no_modelo(modelo: str) -> str | None:
    texto = modelo.strip()
    if not texto:
        return "Preencha o modelo do complemento (ex.: FAVORECIDO - CNPJ - NATUREZA - DOCUMENTO)."
    if ";" in texto:
        return (
            "O modelo do complemento não pode ter ponto e vírgula (;) — o Domínio usa esse sinal no arquivo."
        )
    if not _DIVIDIR.search(texto):
        return "Use no modelo pelo menos uma destas palavras: " + ", ".join(PARTES) + "."
    return None


def montar_complemento(modelo: str, valores: dict[str, str | None]) -> str:
    pedacos = _DIVIDIR.split(modelo)  # [texto, PARTE, texto, PARTE, ..., texto]
    if len(pedacos) == 1:  # modelo sem nenhuma parte conhecida (já recusado por problema_no_modelo)
        return ""
    prefixo, partes, separadores = pedacos[0], pedacos[1::2], pedacos[2::2]
    resultado = prefixo
    separador_pendente = None
    for parte, separador_depois in zip(partes, separadores[:-1] + [""], strict=True):
        valor = _ESPACOS.sub(" ", (valores.get(parte) or "").replace(";", ",")).strip()
        if not valor:
            continue
        if separador_pendente is not None:
            resultado += separador_pendente
        resultado += valor
        separador_pendente = separador_depois
    return (resultado + separadores[-1]).strip()
