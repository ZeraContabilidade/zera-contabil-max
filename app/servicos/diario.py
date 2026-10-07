"""Leitura do Diário exportado do Domínio em Excel (§11.3). O Razão entra aqui quando houver amostra.

Formato: cabeçalho da empresa (“Empresa:”, “C.N.P.J.:”, “Período:”), depois os títulos
`Data | Classificação | Descrição | Histórico | Débito | Crédito`. Cada linha tem UM lado só
(débito ou crédito); os lançamentos do dia fecham em “TOTAL DO DIA” e “TOTAL DO MÊS”.

O leitor junta as linhas em partidas (débito × crédito):
- Diário completo (todo dia fecha débito = crédito): as linhas seguidas são somadas até fechar;
  cada grupo vira 1 × N partidas (um débito contra vários créditos, ou o contrário).
- Diário impresso só com algumas contas (ex.: só o Passivo): o dia não fecha. Só viram partida duas
  linhas seguidas de lados opostos, mesmo valor e mesmo histórico; as outras ficam com um lado só.
"""

import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import groupby
from typing import Any

from python_calamine import CalamineWorkbook

from app.servicos.contas_chave import normalizar
from app.servicos.documentos import normalizar_documento, tipo_documento
from app.servicos.plano import Aviso, ErroLeitura

_TITULOS = {
    "data": lambda t: t == "DATA",
    "classificacao": lambda t: t.startswith("CLASSIF"),
    "descricao": lambda t: t.startswith("DESCRI") or t == "CONTA",
    "historico": lambda t: t.startswith("HISTOR"),
    "debito": lambda t: t.startswith("DEBITO"),
    "credito": lambda t: t.startswith("CREDITO"),
}
_OBRIGATORIAS = {"data", "classificacao", "historico", "debito", "credito"}
_CABECALHO = {"EMPRESA:": "empresa", "C.N.P.J.:": "cnpj", "CNPJ:": "cnpj", "PERIODO:": "periodo"}


@dataclass
class LinhaDiario:
    numero: int  # linha da planilha (1 = primeira)
    data: date
    classificacao: str  # só os dígitos: 21502000002
    descricao: str  # nome da conta como saiu no Diário
    historico: str
    valor: Decimal
    lado: str  # "D" ou "C"


@dataclass
class Partida:
    data: date
    debito: LinhaDiario | None  # None = o lado não está no arquivo
    credito: LinhaDiario | None
    valor: Decimal
    historico: str

    @property
    def numero(self) -> int:
        return (self.debito or self.credito).numero


@dataclass
class DiarioLido:
    empresa: str | None = None
    cnpj: str | None = None  # só quando o dígito confere
    periodo: str | None = None
    linhas: list[LinhaDiario] = field(default_factory=list)
    partidas: list[Partida] = field(default_factory=list)
    completo: bool = True  # todos os dias fecham débito = crédito
    avisos: list[Aviso] = field(default_factory=list)

    @property
    def um_lado(self) -> int:
        return sum(1 for p in self.partidas if p.debito is None or p.credito is None)


def eh_planilha(conteudo: bytes) -> bool:
    """.xls (formato antigo do Office) ou .xlsx (zip)."""
    return conteudo.startswith((b"\xd0\xcf\x11\xe0", b"PK\x03\x04"))


def _abrir(conteudo: bytes) -> list[list[Any]]:
    try:
        planilha = CalamineWorkbook.from_filelike(io.BytesIO(conteudo))
    except Exception as erro:
        raise ErroLeitura("Não consegui abrir a planilha. Salve como .xlsx no Excel e envie de novo.") from erro
    for nome in planilha.sheet_names:
        linhas = planilha.get_sheet_by_name(nome).to_python(skip_empty_area=False)
        if _achar_titulos(linhas) is not None:
            return linhas
    raise ErroLeitura(
        "Esta planilha não parece um Diário do Domínio: não achei as colunas "
        "Data, Classificação, Histórico, Débito e Crédito."
    )


def _achar_titulos(linhas: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    for indice, linha in enumerate(linhas[:40]):
        posicoes: dict[str, int] = {}
        for coluna, celula in enumerate(linha):
            titulo = normalizar(str(celula)) if celula not in (None, "") else ""
            for nome, combina in _TITULOS.items():
                if titulo and nome not in posicoes and combina(titulo):
                    posicoes[nome] = coluna
                    break
        if _OBRIGATORIAS <= posicoes.keys():
            return indice, posicoes
    return None


def _data(celula: Any) -> date | None:
    if isinstance(celula, datetime):
        return celula.date()
    if isinstance(celula, date):
        return celula
    try:
        return datetime.strptime(str(celula).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _valor(celula: Any) -> Decimal | None:
    """1234.5 (número do Excel) ou '1.234,50' (texto) → Decimal('1234.50'). Vazio ou zero → None."""
    if celula in (None, ""):
        return None
    texto = str(celula).strip().replace("R$", "").strip()
    if not isinstance(celula, int | float) and "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return valor if valor else None


def _ler_cabecalho(linhas: list[list[Any]], ate: int, lido: DiarioLido) -> None:
    for linha in linhas[:ate]:
        celulas = [c for c in linha if c not in (None, "")]
        for posicao, celula in enumerate(celulas[:-1]):
            campo = _CABECALHO.get(normalizar(str(celula)))
            if campo and getattr(lido, campo) is None:
                setattr(lido, campo, " ".join(str(celulas[posicao + 1]).split()))
    if lido.cnpj:
        documento = normalizar_documento(lido.cnpj)
        lido.cnpj = documento if tipo_documento(documento) else None


def _partir(grupo: list[LinhaDiario]) -> list[Partida]:
    """Um grupo que fecha débito = crédito → partidas 1 × N."""
    debitos = [linha for linha in grupo if linha.lado == "D"]
    creditos = [linha for linha in grupo if linha.lado == "C"]
    if len(debitos) == 1:
        return [Partida(c.data, debitos[0], c, c.valor, c.historico or debitos[0].historico) for c in creditos]
    if len(creditos) == 1:
        return [Partida(d.data, d, creditos[0], d.valor, d.historico or creditos[0].historico) for d in debitos]
    # vários contra vários (raro): junta os de mesmo valor; o que sobrar fica com um lado só
    partidas, sobra = [], list(creditos)
    for debito in debitos:
        par = next((c for c in sobra if c.valor == debito.valor), None)
        if par:
            sobra.remove(par)
            partidas.append(Partida(debito.data, debito, par, debito.valor, debito.historico or par.historico))
        else:
            partidas.append(_um_lado(debito))
    return partidas + [_um_lado(c) for c in sobra]


def _um_lado(linha: LinhaDiario) -> Partida:
    if linha.lado == "D":
        return Partida(linha.data, linha, None, linha.valor, linha.historico)
    return Partida(linha.data, None, linha, linha.valor, linha.historico)


def _fecha(linhas: list[LinhaDiario]) -> bool:
    debito = sum((linha.valor for linha in linhas if linha.lado == "D"), Decimal("0"))
    credito = sum((linha.valor for linha in linhas if linha.lado == "C"), Decimal("0"))
    return debito == credito


def _partidas_do_dia_completo(linhas: list[LinhaDiario]) -> list[Partida]:
    partidas, grupo = [], []
    for linha in linhas:
        grupo.append(linha)
        if {item.lado for item in grupo} == {"D", "C"} and _fecha(grupo):
            partidas += _partir(grupo)
            grupo = []
    return partidas + [_um_lado(linha) for linha in grupo]


def _partidas_do_dia_incompleto(linhas: list[LinhaDiario]) -> list[Partida]:
    partidas, i = [], 0
    while i < len(linhas):
        linha, seguinte = linhas[i], linhas[i + 1] if i + 1 < len(linhas) else None
        if (
            seguinte
            and seguinte.lado != linha.lado
            and seguinte.valor == linha.valor
            and normalizar(seguinte.historico) == normalizar(linha.historico)
        ):
            debito, credito = (linha, seguinte) if linha.lado == "D" else (seguinte, linha)
            partidas.append(Partida(linha.data, debito, credito, linha.valor, linha.historico))
            i += 2
        else:
            partidas.append(_um_lado(linha))
            i += 1
    return partidas


def ler_diario(conteudo: bytes) -> DiarioLido:
    linhas = _abrir(conteudo)
    inicio, colunas = _achar_titulos(linhas)
    lido = DiarioLido()
    _ler_cabecalho(linhas, inicio, lido)

    def celula(linha: list[Any], nome: str) -> Any:
        posicao = colunas.get(nome)
        return linha[posicao] if posicao is not None and posicao < len(linha) else None

    dois_lados, sem_valor = [], []
    for numero, linha in enumerate(linhas[inicio + 1 :], start=inicio + 2):
        data = _data(celula(linha, "data"))
        classificacao = "".join(ch for ch in str(celula(linha, "classificacao") or "") if ch.isalnum())
        if data is None or not classificacao:
            continue  # “TOTAL DO DIA”, “TOTAL DO MÊS”, linhas vazias, rodapé com as assinaturas
        debito, credito = _valor(celula(linha, "debito")), _valor(celula(linha, "credito"))
        historico = " ".join(str(celula(linha, "historico") or "").split())
        if debito and credito:
            dois_lados.append(f"Linha {numero}: {historico[:60]}")
            continue
        if not (debito or credito) or (debito or credito) < 0:
            sem_valor.append(f"Linha {numero}: {historico[:60]}")
            continue
        lido.linhas.append(
            LinhaDiario(
                numero=numero,
                data=data,
                classificacao=classificacao,
                descricao=" ".join(str(celula(linha, "descricao") or "").split()),
                historico=historico,
                valor=debito or credito,
                lado="D" if debito else "C",
            )
        )
    if not lido.linhas:
        raise ErroLeitura("Não encontrei nenhum lançamento no Diário. Confira se o arquivo é o Diário do Domínio.")

    dias = [list(itens) for _, itens in groupby(lido.linhas, key=lambda linha: linha.data)]
    lido.completo = all(_fecha(dia) for dia in dias)
    montar = _partidas_do_dia_completo if lido.completo else _partidas_do_dia_incompleto
    for dia in dias:
        lido.partidas += montar(dia)

    if not lido.completo:
        grupos = Counter(linha.classificacao[:1] for linha in lido.linhas)
        lido.avisos.append(
            Aviso(
                "O Diário veio só com algumas contas (os dias não fecham débito = crédito): "
                f"{lido.um_lado} lançamento(s) entraram com um lado só. Para o sistema aprender mais "
                "(inclusive as contas de banco), gere no Domínio o Diário com TODAS as contas.",
                [f"Contas do grupo {g}: {n} linha(s)" for g, n in sorted(grupos.items())],
            )
        )
    if dois_lados:
        lido.avisos.append(
            Aviso(f"{len(dois_lados)} linha(s) com débito e crédito ao mesmo tempo, ignoradas.", dois_lados)
        )
    if sem_valor:
        lido.avisos.append(Aviso(f"{len(sem_valor)} linha(s) sem valor válido, ignoradas.", sem_valor))
    return lido
