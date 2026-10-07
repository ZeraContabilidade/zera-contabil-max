"""Arquivo lanctos.txt de importação de lançamentos no Domínio (§11.1).

data;débito;crédito;valor;cód. histórico;complemento;inicia lote;código da empresa;cc débito;cc crédito
Separador “;”, sem cabeçalho, CRLF, Windows-1252, valor com vírgula decimal e sem separador de milhar.
Aqui fica a LEITURA (aprender com arquivos antigos, §11.5); a geração vem na etapa 3.1.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.servicos.competencia import hoje
from app.servicos.plano import Aviso, ErroLeitura

_DATA = re.compile(r"^\s*\d{1,2}/+\d{1,2}/+\d{4}\s*;")


@dataclass
class LinhaLanctos:
    numero: int  # linha no arquivo
    data: date
    debito: int
    credito: int
    valor: Decimal
    complemento: str
    codigo_empresa: int | None


def parece_lanctos(texto: str) -> bool:
    uteis = [linha for linha in texto.splitlines() if linha.strip()]
    bons = sum(1 for linha in uteis if _DATA.match(linha) and linha.count(";") >= 7)
    return bool(uteis) and bons >= 0.8 * len(uteis)


def _conta(texto: str) -> tuple[int | None, bool]:
    """'10595.' → (10595, corrigida=True)."""
    achado = re.fullmatch(r"\s*(\d+)\s*(\.?)\s*", texto)
    return (int(achado.group(1)), bool(achado.group(2))) if achado else (None, False)


def _valor(texto: str) -> Decimal | None:
    texto = texto.strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    return valor if valor > 0 else None


def ler_lanctos(texto: str) -> tuple[list[LinhaLanctos], list[Aviso]]:
    linhas, corrigidas, ignoradas, futuras = [], [], [], []
    limite = hoje()
    for numero, bruta in enumerate(texto.splitlines(), start=1):
        if not bruta.strip():
            continue
        campos = bruta.split(";")
        if len(campos) < 8:
            ignoradas.append(f"Linha {numero}: menos campos que o formato do Domínio")
            continue
        data_texto = campos[0].strip()
        data_limpa = re.sub(r"/+", "/", data_texto)
        try:
            data = datetime.strptime(data_limpa, "%d/%m/%Y").date()
        except ValueError:
            ignoradas.append(f"Linha {numero}: data inválida “{data_texto}”")
            continue
        if data_limpa != data_texto:
            corrigidas.append(f"Linha {numero}: data “{data_texto}” lida como {data_limpa}")
        if data > limite:
            futuras.append(f"Linha {numero}: {data_limpa} — {campos[5].strip()[:60]}")

        debito, ponto_debito = _conta(campos[1])
        credito, ponto_credito = _conta(campos[2])
        valor = _valor(campos[3])
        if debito is None or credito is None or valor is None:
            ignoradas.append(f"Linha {numero}: conta ou valor inválido ({campos[1]}; {campos[2]}; {campos[3]})")
            continue
        for ponto, original in ((ponto_debito, campos[1]), (ponto_credito, campos[2])):
            if ponto:
                corrigidas.append(f"Linha {numero}: conta “{original.strip()}” lida como {original.strip(' .')}")
        codigo = campos[7].strip()
        linhas.append(
            LinhaLanctos(
                numero=numero,
                data=data,
                debito=debito,
                credito=credito,
                valor=valor,
                complemento=" ".join(campos[5].split()),
                codigo_empresa=int(codigo) if codigo.isdigit() else None,
            )
        )
    if not linhas:
        raise ErroLeitura("Não encontrei nenhum lançamento no arquivo. Confira se é o lanctos.txt do Domínio.")
    avisos = []
    if corrigidas:
        avisos.append(
            Aviso(
                f"{len(corrigidas)} erro(s) de digitação corrigido(s) na leitura — o Domínio recusaria estas linhas.",
                corrigidas,
            )
        )
    if futuras:
        avisos.append(Aviso(f"{len(futuras)} lançamento(s) com data no futuro (provável erro de digitação).", futuras))
    if ignoradas:
        avisos.append(Aviso(f"{len(ignoradas)} linha(s) ignorada(s) por estarem fora do formato.", ignoradas))
    return linhas, avisos
