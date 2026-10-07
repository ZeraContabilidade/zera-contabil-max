"""Extrato em planilha (Excel .xlsx/.xls ou CSV) de qualquer banco (§3.4, regras 3 e 5).

Aqui fica só a LEITURA: abrir o arquivo, achar a linha de títulos, a assinatura do layout e montar os
movimentos com as colunas escolhidas. Quem decide as colunas (títulos, IA ou o usuário, uma vez por layout)
e a conta bancária é `app/servicos/planilha_extrato.py`.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from python_calamine import CalamineWorkbook

from app.leitores import MovimentoLido
from app.servicos.contas_chave import normalizar
from app.servicos.diario import eh_planilha
from app.servicos.plano import Aviso, ErroLeitura, decodificar

PAPEIS = ("data", "historico", "complemento", "documento", "valor", "debito", "credito", "sentido", "saldo")
NOMES_PAPEIS = {
    "data": "Data",
    "historico": "Histórico / descrição",
    "complemento": "Complemento / favorecido",
    "documento": "Documento",
    "valor": "Valor (com sinal)",
    "debito": "Débito / saída",
    "credito": "Crédito / entrada",
    "sentido": "C/D",
    "saldo": "Saldo",
}
_TITULOS = {
    "data": re.compile(r"^(DATA|DT\.?)( (LANC|LANCAMENTO|MOVIMENTO|MOV)\.?)?$"),
    "historico": re.compile(r"^(HISTORICO|DESCRICAO|LANCAMENTO|LANCAMENTOS|DESCRICAO DO LANCAMENTO|MOVIMENTACAO)$"),
    "complemento": re.compile(r"^(COMPLEMENTO|FAVORECIDO|DETALHES|INFORMACOES|INFORMACOES ADICIONAIS)$"),
    "documento": re.compile(r"^(DOCUMENTO|DOC\.?|N. DOCUMENTO|NUMERO DO DOCUMENTO|NR\. DOC\.?)$"),
    "valor": re.compile(r"^VALOR( \(R\$\)| R\$)?$"),
    "debito": re.compile(r"^(DEBITO|DEBITOS|SAIDA|SAIDAS|VALOR DEBITO)( \(R\$\))?$"),
    "credito": re.compile(r"^(CREDITO|CREDITOS|ENTRADA|ENTRADAS|VALOR CREDITO)( \(R\$\))?$"),
    "sentido": re.compile(r"^(C/D|D/C|TIPO|NATUREZA)$"),
    "saldo": re.compile(r"^SALDO( \(R\$\)| R\$| DO DIA)?$"),
}


class _PontoEVirgula(csv.excel):
    delimiter = ";"  # padrão das planilhas brasileiras


def parece_planilha(nome: str, conteudo: bytes) -> bool:
    """Excel pelo conteúdo; CSV = texto com 3+ linhas que têm o mesmo separador."""
    if eh_planilha(conteudo):
        return True
    if conteudo.lstrip()[:5] == b"%PDF-" or b"<OFX>" in conteudo.upper()[:5000]:
        return False
    linhas = [linha for linha in decodificar(conteudo[:20000]).splitlines() if linha.strip()]
    return len(linhas) >= 3 and any(sum(1 for linha in linhas[:20] if linha.count(s) >= 2) >= 3 for s in ";,\t")


def ler_linhas(conteudo: bytes) -> list[list[Any]]:
    """Linhas da planilha (a aba com mais datas) ou do CSV, sem as linhas vazias do fim."""
    if eh_planilha(conteudo):
        try:
            livro = CalamineWorkbook.from_filelike(io.BytesIO(conteudo))
        except Exception as erro:
            raise ErroLeitura("Não consegui abrir a planilha. Salve como .xlsx no Excel e envie de novo.") from erro
        abas = [livro.get_sheet_by_name(nome).to_python(skip_empty_area=False) for nome in livro.sheet_names]
        linhas = max(abas, key=lambda aba: sum(1 for linha in aba for c in linha if valor_data(c)), default=[])
    else:
        texto = decodificar(conteudo)
        try:
            dialeto = csv.Sniffer().sniff(texto[:5000], delimiters=";,\t")
        except csv.Error:
            dialeto = _PontoEVirgula
        linhas = list(csv.reader(io.StringIO(texto), dialeto))
    while linhas and not any(str(c).strip() for c in linhas[-1] if c is not None):
        linhas.pop()
    return linhas


def texto_celula(celula: Any) -> str:
    if celula is None:
        return ""
    if isinstance(celula, datetime | date):
        return celula.strftime("%d/%m/%Y")
    if isinstance(celula, float) and celula.is_integer():
        return str(int(celula))
    return " ".join(str(celula).split())


def valor_data(celula: Any) -> date | None:
    if isinstance(celula, datetime):
        return celula.date()
    if isinstance(celula, date):
        return celula
    texto = texto_celula(celula)
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def valor_dinheiro(celula: Any) -> Decimal | None:
    """Número do Excel, '1.234,56', '-1.234,56', '1234.56', '(1.234,56)' ou '1.234,56 D' → Decimal com sinal."""
    if celula is None or celula == "":
        return None
    if isinstance(celula, int | float):
        return Decimal(str(celula)).quantize(Decimal("0.01"))
    texto = texto_celula(celula).upper().replace("R$", "").replace(" ", "")
    negativo = texto.startswith("-") or texto.endswith("-") or texto.endswith("D") or texto.startswith("(")
    texto = texto.strip("-+()CD")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1:
        texto = texto.replace(".", "")
    try:
        valor = Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -valor if negativo else valor


def achar_titulos(linhas: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    """Linha de títulos e colunas pelos nomes comuns. Precisa de data, histórico e valor (ou débito/crédito)."""
    for indice, linha in enumerate(linhas[:30]):
        colunas: dict[str, int] = {}
        for posicao, celula in enumerate(linha):
            titulo = normalizar(texto_celula(celula)).rstrip(":")
            for papel, padrao in _TITULOS.items():
                if titulo and papel not in colunas and padrao.match(titulo):
                    colunas[papel] = posicao
                    break
        tem_valor = "valor" in colunas or ("debito" in colunas and "credito" in colunas)
        if "data" in colunas and "historico" in colunas and tem_valor:
            return indice, completar(colunas)
    return None


def completar(colunas: dict[str, int]) -> dict[str, int]:
    return {papel: int(colunas.get(papel, -1)) for papel in PAPEIS}


def assinatura(linhas: list[list[Any]], linha_titulos: int) -> str:
    """Impressão digital do layout: os títulos normalizados (ou, sem títulos, o nº de colunas)."""
    if 0 <= linha_titulos < len(linhas):
        base = "|".join(normalizar(texto_celula(c)) for c in linhas[linha_titulos])
    else:
        base = f"sem-titulos|{max((len(linha) for linha in linhas), default=0)}"
    return hashlib.sha256(base.encode()).hexdigest()


def titulos(linhas: list[list[Any]], linha_titulos: int) -> list[str]:
    if 0 <= linha_titulos < len(linhas):
        return [texto_celula(c) for c in linhas[linha_titulos]]
    return [f"Coluna {i + 1}" for i in range(max((len(linha) for linha in linhas), default=0))]


@dataclass
class Montagem:
    movimentos: list[MovimentoLido] = field(default_factory=list)
    saldo_inicial: Decimal | None = None
    saldo_final: Decimal | None = None
    avisos: list[Aviso] = field(default_factory=list)


def montar(linhas: list[list[Any]], linha_titulos: int, colunas: dict[str, int]) -> Montagem:
    """Movimentos com as colunas escolhidas. Linhas de saldo (“SALDO ANTERIOR”, “SALDO DO DIA”) viram saldo.
    Sem linha de saldo anterior, mas com coluna de saldo: o inicial sai do saldo da 1ª linha menos o 1º movimento."""

    def celula(linha: list[Any], papel: str) -> Any:
        posicao = colunas.get(papel, -1)
        return linha[posicao] if 0 <= posicao < len(linha) else None

    resultado, ignoradas = Montagem(), []
    primeiro_saldo = None
    for numero, linha in enumerate(linhas[linha_titulos + 1 :], start=linha_titulos + 2):
        dia = valor_data(celula(linha, "data"))
        historico = texto_celula(celula(linha, "historico"))
        saldo = valor_dinheiro(celula(linha, "saldo"))
        if dia is None:
            continue  # títulos repetidos, totais, rodapé
        titulo = normalizar(historico).replace("S A L D O", "SALDO")
        if titulo.startswith("SALDO"):
            if "ANTERIOR" in titulo or "INICIAL" in titulo:
                valor_saldo = saldo if saldo is not None else valor_dinheiro(celula(linha, "valor"))
                if resultado.saldo_inicial is None and not resultado.movimentos:
                    resultado.saldo_inicial = valor_saldo
            elif saldo is not None or valor_dinheiro(celula(linha, "valor")) is not None:
                resultado.saldo_final = saldo if saldo is not None else valor_dinheiro(celula(linha, "valor"))
            continue
        valor, sentido = _valor_e_sentido(linha, celula)
        if valor is None:
            ignoradas.append(f"Linha {numero}: {historico[:60]}")
            continue
        if primeiro_saldo is None and saldo is not None:
            primeiro_saldo = (saldo, valor if sentido == "ENTRADA" else -valor)
        if saldo is not None:
            resultado.saldo_final = saldo
        resultado.movimentos.append(
            MovimentoLido(
                data=dia,
                valor=valor,
                sentido=sentido,
                historico=historico[:120] or "Movimento",
                complemento=texto_celula(celula(linha, "complemento"))[:200],
                documento=texto_celula(celula(linha, "documento"))[:60],
            )
        )
    if resultado.saldo_inicial is None and primeiro_saldo is not None:
        resultado.saldo_inicial = primeiro_saldo[0] - primeiro_saldo[1]
    if ignoradas:
        resultado.avisos.append(Aviso(f"{len(ignoradas)} linha(s) com data mas sem valor foram ignoradas.", ignoradas))
    return resultado


def _valor_e_sentido(linha: list[Any], celula) -> tuple[Decimal | None, str]:
    debito, credito = valor_dinheiro(celula(linha, "debito")), valor_dinheiro(celula(linha, "credito"))
    if debito:
        return abs(debito), "SAIDA"
    if credito:
        return abs(credito), "ENTRADA"
    valor = valor_dinheiro(celula(linha, "valor"))
    if not valor:
        return None, ""
    marca = normalizar(texto_celula(celula(linha, "sentido")))
    if marca in ("D", "DEBITO", "SAIDA", "-"):
        return abs(valor), "SAIDA"
    if marca in ("C", "CREDITO", "ENTRADA", "+"):
        return abs(valor), "ENTRADA"
    return abs(valor), "ENTRADA" if valor > 0 else "SAIDA"
