"""CNPJ e CPF: limpeza, validação dos dígitos e formatação.

Aceita o CNPJ alfanumérico (letras nas 12 primeiras posições), emitido pela Receita
desde julho/2026: no cálculo do dígito cada caractere vale (código ASCII − 48),
o que mantém os números iguais ao cálculo antigo.
"""

import re

_SO_LETRAS_E_NUMEROS = re.compile(r"[^0-9A-Z]")
_FORMATO_CNPJ = re.compile(r"[0-9A-Z]{12}[0-9]{2}")
_PESOS_DV1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_PESOS_DV2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def normalizar_documento(texto: str | None) -> str:
    """'06.101.084/0001-36' → '06101084000136' (maiúsculas, sem pontuação)."""
    return _SO_LETRAS_E_NUMEROS.sub("", (texto or "").upper())


def _digito(parte: str, pesos: tuple[int, ...]) -> str:
    resto = sum((ord(c) - 48) * p for c, p in zip(parte, pesos, strict=True)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(texto: str | None) -> bool:
    cnpj = normalizar_documento(texto)
    if not _FORMATO_CNPJ.fullmatch(cnpj) or len(set(cnpj)) == 1:
        return False
    dv1 = _digito(cnpj[:12], _PESOS_DV1)
    dv2 = _digito(cnpj[:12] + dv1, _PESOS_DV2)
    return cnpj[12:] == dv1 + dv2


def cpf_valido(texto: str | None) -> bool:
    cpf = normalizar_documento(texto)
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        if str(soma * 10 % 11 % 10) != cpf[tamanho]:
            return False
    return True


def tipo_documento(texto: str | None) -> str | None:
    """'CNPJ', 'CPF' ou None quando não é um documento válido."""
    if cnpj_valido(texto):
        return "CNPJ"
    if cpf_valido(texto):
        return "CPF"
    return None


def formatar_documento(texto: str | None) -> str:
    doc = normalizar_documento(texto)
    if len(doc) == 14:
        return f"{doc[:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:]}"
    if len(doc) == 11:
        return f"{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}"
    return doc
