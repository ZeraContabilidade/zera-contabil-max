"""O `lanctos.txt` que o Domínio importa (§3.6, §11.1) — igual, byte a byte, ao que a macro `Gerar()` da planilha
EXPORTAÇÃO DOMINIO.xlsm gravava e o Domínio já aceita:

    05/01/2026;492;8;150,17;;QUATAI TRANSPORTE ... - VALE TRANSPORTE - 841;1;230;;

10 campos separados por “;” (data; débito; crédito; valor; cód. histórico vazio; complemento; inicia lote = 1;
código da empresa; c. custo débito e crédito vazios), sem cabeçalho, quebra de linha CRLF, Windows-1252. Valor com
vírgula, sem milhar e sem zeros sobrando (346,5 · 120). Conta em branco é aceita pelo Domínio (decisão de 08/10).

`conferir_txt` confere um arquivo pronto linha a linha (o modelo do escritório tinha 3 erros: “28/01//2026”,
“28/01//2027” e a conta “10595.”) — o sistema confere o que ele mesmo gera antes de entregar.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.modelos import ContaContabil

SEPARADOR = ";"
QUEBRA = "\r\n"
CODIFICACAO = "cp1252"
CAMPOS = 10
_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_CONTA = re.compile(r"^\d+$")
_VALOR = re.compile(r"^\d+(,\d{1,2})?$")


@dataclass(frozen=True)
class LinhaLancto:
    data: date
    debito: int | None  # código reduzido; None = em branco (conta fora do plano — completa no Domínio)
    credito: int | None
    valor: Decimal
    complemento: str


def formatar_valor(valor: Decimal) -> str:
    """Como a macro gravava: vírgula decimal, sem milhar e sem zeros sobrando (150,17 · 346,5 · 120)."""
    inteiro, _, centavos = f"{valor.quantize(Decimal('0.01')):f}".partition(".")
    centavos = centavos.rstrip("0")
    return f"{inteiro},{centavos}" if centavos else inteiro


def texto_windows(texto: str) -> str:
    """Só o que o Windows-1252 grava (letra fora dele perde o acento ou some); sem quebra de linha nem tabulação."""
    saida = []
    for letra in " ".join((texto or "").replace("\t", " ").splitlines()):
        try:
            letra.encode(CODIFICACAO)
            saida.append(letra)
        except UnicodeEncodeError:
            saida.append(unicodedata.normalize("NFKD", letra).encode(CODIFICACAO, "ignore").decode(CODIFICACAO))
    return "".join(saida)


def linha_txt(linha: LinhaLancto, codigo_empresa: int) -> str:
    campos = [
        f"{linha.data:%d/%m/%Y}",
        str(linha.debito or ""),
        str(linha.credito or ""),
        formatar_valor(linha.valor),
        "",  # código do histórico (não usado)
        texto_windows(linha.complemento),
        "1",  # inicia lote
        str(codigo_empresa),
        "",  # centro de custo débito
        "",  # centro de custo crédito
    ]
    return SEPARADOR.join(campos)


def gerar_txt(linhas: list[LinhaLancto], codigo_empresa: int) -> bytes:
    return "".join(linha_txt(linha, codigo_empresa) + QUEBRA for linha in linhas).encode(CODIFICACAO)


def ler_txt(conteudo: bytes) -> list[LinhaLancto]:
    """Lê um lanctos.txt já conferido (sem erros) de volta em linhas — usado nos testes do arquivo de ouro."""
    linhas = []
    for texto in conteudo.decode(CODIFICACAO).split(QUEBRA):
        if not texto:
            continue
        campos = texto.split(SEPARADOR)
        linhas.append(
            LinhaLancto(
                datetime.strptime(campos[0], "%d/%m/%Y").date(),
                int(campos[1]) if campos[1] else None,
                int(campos[2]) if campos[2] else None,
                Decimal(campos[3].replace(",", ".")),
                campos[5],
            )
        )
    return linhas


# ---------------------------------------------------------------- conferência do arquivo pronto


@dataclass(frozen=True)
class Problema:
    linha: int  # nº da linha no arquivo (a 1ª é 1)
    texto: str


def _conferir_conta(numero: int, lado: str, campo: str, contas: dict[int, ContaContabil] | None) -> str | None:
    if not campo:
        return None  # em branco: o Domínio aceita
    if not _CONTA.match(campo):
        return f"Linha {numero}: conta {lado} “{campo}” inválida (só o código reduzido, ex.: 355)."
    if contas is None:
        return None
    conta = contas.get(int(campo))
    if conta is None or not conta.ativa:
        return f"Linha {numero}: a conta {lado} {campo} não existe no plano de contas desta empresa."
    if not conta.analitica:
        return f"Linha {numero}: a conta {lado} {conta.rotulo} é sintética (grupo): use uma conta analítica."
    return None


def conferir_txt(
    conteudo: bytes,
    contas: dict[int, ContaContabil] | None = None,
    inicio: date | None = None,
    fim: date | None = None,
    codigo_empresa: int | None = None,
) -> list[Problema]:
    """Confere um lanctos.txt linha a linha. `contas` = plano da empresa por código reduzido (None = não confere)."""
    try:
        texto = conteudo.decode(CODIFICACAO)
    except UnicodeDecodeError:
        return [Problema(0, "O arquivo não está em Windows-1252 (o Domínio não lê os acentos).")]
    problemas = []
    if "\n" in texto.replace(QUEBRA, "") or (texto and not texto.endswith(QUEBRA)):
        problemas.append(Problema(0, "O arquivo tem de usar quebra de linha do Windows (CRLF), inclusive na última."))
    for numero, linha in enumerate(texto.replace(QUEBRA, "\n").split("\n"), 1):
        if not linha:
            continue
        campos = linha.split(SEPARADOR)
        if len(campos) != CAMPOS:
            problemas.append(
                Problema(
                    numero, f"Linha {numero}: tem {len(campos)} campos em vez de {CAMPOS} (há “;” no complemento?)."
                )
            )
            continue
        data, debito, credito, valor, _, _, lote, codigo, _, _ = campos
        erros = []
        quando = None
        if _DATA.match(data):
            try:
                quando = datetime.strptime(data, "%d/%m/%Y").date()
            except ValueError:
                pass
        if quando is None:
            erros.append(f"Linha {numero}: data “{data}” inválida (use dd/mm/aaaa).")
        elif (inicio and quando < inicio) or (fim and quando > fim):
            erros.append(f"Linha {numero}: data {data} fora do período exportado.")
        erros += [e for e in (_conferir_conta(numero, "débito", debito, contas),
                              _conferir_conta(numero, "crédito", credito, contas)) if e]  # fmt: skip
        if not debito and not credito:
            erros.append(f"Linha {numero}: débito e crédito em branco.")
        elif debito and debito == credito:
            erros.append(f"Linha {numero}: débito e crédito na mesma conta ({debito}).")
        try:
            valido = bool(_VALOR.match(valor)) and Decimal(valor.replace(",", ".")) > 0
        except InvalidOperation:
            valido = False
        if not valido:
            erros.append(f"Linha {numero}: valor “{valor}” inválido (maior que zero, vírgula decimal, ex.: 150,17).")
        if lote != "1":
            erros.append(f"Linha {numero}: o campo “inicia lote” tem de ser 1.")
        if codigo_empresa is not None and codigo != str(codigo_empresa):
            erros.append(f"Linha {numero}: código da empresa {codigo} diferente de {codigo_empresa}.")
        problemas += [Problema(numero, erro) for erro in erros]
    return problemas
