"""Plano de contas: leitura do arquivo (TXT do Domínio, Excel ou CSV) e importação/reimportação (§3.2, §11.2).

TXT do Domínio — largura fixa, Windows-1252: col. 1–7 reduzido · 8–27 classificação sem pontos ·
28–67 descrição (o Domínio corta em 40 letras) · 68 tipo S/A. A última linha (só 9) é ignorada.
O formato é reconhecido pelo conteúdo, não pela extensão (a amostra da Casa Criança veio como .csv).
"""

import csv
import io
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from python_calamine import CalamineWorkbook
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.modelos import ArquivoOriginal, ContaContabil, Empresa, Importacao, Usuario

EXEMPLOS = 5  # quantos casos aparecem no texto do aviso (a lista completa fica nos detalhes)
TAMANHO_DESCRICAO_DOMINIO = 40


class ErroLeitura(Exception):
    """Arquivo que não dá para ler; a mensagem diz o que fazer."""


@dataclass
class Aviso:
    texto: str
    itens: list[str] = field(default_factory=list)


@dataclass
class ContaLida:
    reduzido: int
    classificacao: str  # só dígitos
    descricao: str
    tipo: str | None  # "S"/"A" como veio no arquivo; None quando não veio ou veio inválido
    linha: int


@dataclass
class ContaPronta:
    reduzido: int
    classificacao: str
    classificacao_formatada: str
    descricao: str
    tipo: str
    nivel: int


@dataclass
class PlanoPronto:
    contas: list[ContaPronta]
    formato: str
    mascara: str
    avisos: list[Aviso]


# ---------------------------------------------------------------- leitura


def ler_plano(conteudo: bytes, nome_arquivo: str) -> PlanoPronto:
    if not conteudo.strip():
        raise ErroLeitura("O arquivo está vazio. Exporte o plano de novo no Domínio e envie outra vez.")
    if conteudo[:2] == b"PK" or conteudo[:4] == b"\xd0\xcf\x11\xe0":
        contas, avisos = _ler_tabela(_linhas_excel(conteudo))
        return preparar(contas, "Excel", avisos)
    texto = _decodificar(conteudo)
    if _parece_txt_dominio(texto):
        contas, avisos = _ler_txt_dominio(texto)
        return preparar(contas, "TXT do Domínio", avisos)
    contas, avisos = _ler_tabela(_linhas_csv(texto))
    return preparar(contas, "CSV", avisos)


def _decodificar(conteudo: bytes) -> str:
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252", errors="replace")  # padrão do Domínio


def _linha_txt_dominio(linha: str) -> bool:
    return len(linha) >= 68 and linha[:7].isdigit() and linha[7:27].strip().isdigit()


def _parece_txt_dominio(texto: str) -> bool:
    uteis = [linha for linha in texto.splitlines() if linha.strip()]
    return bool(uteis) and sum(map(_linha_txt_dominio, uteis)) >= 0.8 * len(uteis)


def _ler_txt_dominio(texto: str) -> tuple[list[ContaLida], list[Aviso]]:
    contas, ignoradas, cortadas = [], [], []
    for numero, linha in enumerate(texto.splitlines(), start=1):
        if not linha.strip() or set(linha.strip()) == {"9"}:  # linha final do Domínio
            continue
        if not _linha_txt_dominio(linha):
            ignoradas.append(f"Linha {numero}: {linha.strip()[:60]}")
            continue
        tipo = linha[67:].strip().upper()
        conta = ContaLida(
            reduzido=int(linha[:7]),
            classificacao=linha[7:27].strip(),
            descricao=" ".join(linha[27:67].split()),
            tipo=tipo if tipo in ("S", "A") else None,
            linha=numero,
        )
        contas.append(conta)
        if linha[66] != " ":
            cortadas.append(f"{conta.reduzido} – {conta.descricao}")
    avisos = []
    if ignoradas:
        avisos.append(
            Aviso(f"{len(ignoradas)} linha(s) fora do formato do Domínio foram ignoradas.", ignoradas)
        )
    if cortadas:
        avisos.append(
            Aviso(
                f"{len(cortadas)} descrições têm {TAMANHO_DESCRICAO_DOMINIO} letras (o limite do Domínio) "
                "e podem estar cortadas. Não atrapalha a classificação.",
                cortadas,
            )
        )
    return contas, avisos


def _linhas_excel(conteudo: bytes) -> list[list[Any]]:
    try:
        planilha = CalamineWorkbook.from_filelike(io.BytesIO(conteudo))
    except Exception as erro:
        raise ErroLeitura(
            "Não consegui abrir a planilha. Salve como .xlsx no Excel e envie de novo."
        ) from erro
    for nome in planilha.sheet_names:
        linhas = planilha.get_sheet_by_name(nome).to_python(skip_empty_area=False)
        if _achar_cabecalho(linhas) is not None:
            return linhas
    return planilha.get_sheet_by_index(0).to_python() if planilha.sheet_names else []


class _PontoEVirgula(csv.excel):
    delimiter = ";"  # padrão das planilhas brasileiras


def _linhas_csv(texto: str) -> list[list[str]]:
    try:
        dialeto = csv.Sniffer().sniff(texto[:5000], delimiters=";,\t")
    except csv.Error:
        dialeto = _PontoEVirgula
    return list(csv.reader(io.StringIO(texto), dialeto))


def _sem_acento(texto: Any) -> str:
    normal = unicodedata.normalize("NFKD", str(texto if texto is not None else ""))
    return "".join(c for c in normal if not unicodedata.combining(c)).strip().lower()


_COLUNAS = {
    "reduzido": lambda t: "reduz" in t or t in ("codigo", "cod", "cod.", "codigo da conta", "conta"),
    "classificacao": lambda t: "classif" in t,
    "descricao": lambda t: "descri" in t or t in ("nome", "nome da conta", "titulo", "titulo da conta"),
    "tipo": lambda t: t in ("tipo", "s/a", "tipo da conta", "sintetica/analitica"),
}


def _achar_cabecalho(linhas: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    for indice, linha in enumerate(linhas[:20]):
        posicoes: dict[str, int] = {}
        for coluna, valor in enumerate(linha):
            titulo = _sem_acento(valor)
            for nome, combina in _COLUNAS.items():
                if nome not in posicoes and titulo and combina(titulo):
                    posicoes[nome] = coluna
                    break
        if "reduzido" in posicoes and "descricao" in posicoes:
            return indice, posicoes
    return None


def _inteiro(valor: Any) -> int | None:
    texto = str(valor if valor is not None else "").strip()
    try:
        numero = float(texto.replace(",", ".")) if texto else None
    except ValueError:
        return None
    return int(numero) if numero is not None and numero.is_integer() and numero > 0 else None


def _ler_tabela(linhas: list[list[Any]]) -> tuple[list[ContaLida], list[Aviso]]:
    achado = _achar_cabecalho(linhas)
    if achado is None:
        raise ErroLeitura(
            "Não reconheci as colunas da planilha. A primeira linha precisa ter títulos como "
            "“Reduzido”, “Classificação”, “Descrição” e “Tipo” (ou envie o TXT exportado do Domínio)."
        )
    inicio, posicoes = achado

    def valor(linha: list[Any], nome: str) -> Any:
        coluna = posicoes.get(nome)
        return linha[coluna] if coluna is not None and coluna < len(linha) else None

    contas, ignoradas = [], []
    for numero, linha in enumerate(linhas[inicio + 1 :], start=inicio + 2):
        if not any(str(c).strip() for c in linha if c is not None):
            continue
        reduzido = _inteiro(valor(linha, "reduzido"))
        descricao = " ".join(str(valor(linha, "descricao") or "").split())
        if reduzido is None or not descricao:
            ignoradas.append(f"Linha {numero}: código reduzido ou descrição em branco/inválido")
            continue
        tipo = _sem_acento(valor(linha, "tipo"))[:1].upper()
        contas.append(
            ContaLida(
                reduzido=reduzido,
                classificacao=re.sub(r"\D", "", str(valor(linha, "classificacao") or "")),
                descricao=descricao[:120],
                tipo=tipo if tipo in ("S", "A") else None,
                linha=numero,
            )
        )
    avisos = (
        [Aviso(f"{len(ignoradas)} linha(s) da planilha foram ignoradas.", ignoradas)] if ignoradas else []
    )
    return contas, avisos


# ---------------------------------------------------------------- máscara, tipo e conferências


def deduzir_mascara(classificacoes: list[str]) -> list[int]:
    """Tamanhos acumulados de cada nível. Ex.: [1, 2, 3, 5, 11] = máscara 1.1.1.2.6.

    Um tamanho é nível da máscara quando a maioria das classificações mais compridas tem
    o “pai” com esse tamanho no plano. Classificação digitada fora do padrão no Domínio
    (ex.: 11123 numa máscara 1.1.2.2.3.4) quase não tem filhos e fica de fora."""
    unicas = {c for c in classificacoes if c}
    if not unicas:
        return []
    tamanhos = sorted({len(c) for c in unicas})
    mascara = []
    for tamanho in tamanhos[:-1]:
        maiores = [c for c in unicas if len(c) > tamanho]
        com_pai = sum(1 for c in maiores if c[:tamanho] in unicas)
        if com_pai >= len(maiores) / 2:
            mascara.append(tamanho)
    return [*mascara, tamanhos[-1]]


def texto_mascara(mascara: list[int]) -> str:
    return ".".join(str(b - a) for a, b in zip([0, *mascara], mascara, strict=False))


def formatar_classificacao(classificacao: str, mascara: list[int]) -> tuple[str, int, bool]:
    """('11102000001', [1,2,3,5,11]) → ('1.1.1.02.000001', nível 5, dentro da máscara)."""
    partes, inicio = [], 0
    for nivel, fim in enumerate(mascara, start=1):
        if len(classificacao) < fim:
            break
        partes.append(classificacao[inicio:fim])
        inicio = fim
        if len(classificacao) == fim:
            return ".".join(partes), nivel, True
    resto = classificacao[inicio:]
    return ".".join([*partes, resto] if resto else partes), len(partes) + 1, False


def _exemplos(itens: list[str]) -> str:
    return "; ".join(itens[:EXEMPLOS]) + (" …" if len(itens) > EXEMPLOS else "")


def preparar(contas: list[ContaLida], formato: str, avisos: list[Aviso]) -> PlanoPronto:
    if not contas:
        raise ErroLeitura(
            "Não encontrei nenhuma conta no arquivo. Confira se é o plano de contas exportado do Domínio."
        )
    avisos = list(avisos)

    unicas: dict[int, ContaLida] = {}
    repetidos = []
    for conta in contas:
        if conta.reduzido in unicas:
            primeira = unicas[conta.reduzido]
            repetidos.append(f"{conta.reduzido} (linhas {primeira.linha} e {conta.linha})")
        else:
            unicas[conta.reduzido] = conta
    if repetidos:
        avisos.append(
            Aviso(
                f"{len(repetidos)} código(s) reduzido(s) repetido(s) no arquivo — ficou a primeira.",
                repetidos,
            )
        )

    mascara = deduzir_mascara([c.classificacao for c in unicas.values()])
    tem_filhos = {
        c.classificacao[:fim] for c in unicas.values() for fim in mascara if fim < len(c.classificacao)
    }

    prontas, fora_da_mascara, tipo_deduzido = [], [], []
    for conta in unicas.values():
        formatada, nivel, na_mascara = formatar_classificacao(conta.classificacao, mascara)
        tipo = conta.tipo
        if tipo is None:
            tipo = "S" if conta.classificacao in tem_filhos else "A"
            tipo_deduzido.append(
                f"{conta.reduzido} – {conta.descricao} → {'sintética' if tipo == 'S' else 'analítica'}"
            )
        if conta.classificacao and not na_mascara:
            fora_da_mascara.append(f"{formatada} – {conta.reduzido} {conta.descricao}")
        prontas.append(
            ContaPronta(conta.reduzido, conta.classificacao, formatada or "—", conta.descricao, tipo, nivel)
        )

    por_classificacao: dict[str, list[ContaPronta]] = {}
    for conta in prontas:
        if conta.classificacao:
            por_classificacao.setdefault(conta.classificacao, []).append(conta)
    duplicadas = [
        f"{grupo[0].classificacao_formatada} → " + " e ".join(f"{c.reduzido} {c.descricao}" for c in grupo)
        for grupo in por_classificacao.values()
        if len(grupo) > 1
    ]
    if duplicadas:
        avisos.insert(
            0,
            Aviso(
                f"{len(duplicadas)} classificação(ões) aparecem em mais de uma conta "
                f"(ex.: {duplicadas[0]}). Não atrapalha: o sistema trabalha pelo código reduzido; "
                "no Diário, a descrição desempata.",
                duplicadas,
            ),
        )
    if fora_da_mascara:
        avisos.insert(
            0,
            Aviso(
                f"{len(fora_da_mascara)} conta(s) com classificação fora da máscara {texto_mascara(mascara)} "
                f"(ex.: {_exemplos(fora_da_mascara)}). Confira no Domínio.",
                fora_da_mascara,
            ),
        )
    if tipo_deduzido:
        avisos.insert(
            0,
            Aviso(
                f"{len(tipo_deduzido)} conta(s) sem tipo S/A válido: o tipo foi deduzido pela hierarquia.",
                tipo_deduzido,
            ),
        )
    prontas.sort(key=lambda c: (c.classificacao, c.reduzido))
    return PlanoPronto(prontas, formato, texto_mascara(mascara), avisos)


def plano_de_outra_empresa(sessao: Session, origem: Empresa) -> PlanoPronto:
    contas = list(
        sessao.scalars(
            select(ContaContabil).where(ContaContabil.empresa_id == origem.id, ContaContabil.ativa)
        )
    )
    if not contas:
        raise ErroLeitura(f"A empresa {origem.nome} ainda não tem plano de contas para copiar.")
    lidas = [ContaLida(c.reduzido, c.classificacao, c.descricao, c.tipo, 0) for c in contas]
    return preparar(lidas, f"Cópia do plano de {origem.nome} (código {origem.codigo_dominio})", [])


# ---------------------------------------------------------------- importação


def importar_plano(
    sessao: Session,
    empresa: Empresa,
    plano: PlanoPronto,
    usuario: Usuario | None,
    arquivo: ArquivoOriginal | None = None,
) -> Importacao:
    """Grava o plano. Reimportar casa pelo código reduzido e não apaga nada:
    conta que sumiu do arquivo fica desativada, e o aprendizado ligado a ela é mantido."""
    existentes = {
        c.reduzido: c
        for c in sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id))
    }
    novas = alteradas = reativadas = 0
    for pronta in plano.contas:
        campos = asdict(pronta)
        conta = existentes.pop(pronta.reduzido, None)
        if conta is None:
            sessao.add(ContaContabil(empresa_id=empresa.id, **campos))
            novas += 1
            continue
        if not conta.ativa:
            conta.ativa = True
            reativadas += 1
        if any(getattr(conta, chave) != valor for chave, valor in campos.items()):
            for chave, valor in campos.items():
                setattr(conta, chave, valor)
            alteradas += 1

    removidas = sorted((c for c in existentes.values() if c.ativa), key=lambda c: c.reduzido)
    for conta in removidas:
        conta.ativa = False

    avisos = list(plano.avisos)
    if removidas:
        avisos.insert(
            0,
            Aviso(
                f"{len(removidas)} conta(s) não estão mais no plano e foram desativadas "
                f"(ex.: {_exemplos([c.rotulo for c in removidas])}). O aprendizado ligado a elas é mantido.",
                [c.rotulo for c in removidas],
            ),
        )
    analiticas = sum(1 for c in plano.contas if c.tipo == "A")
    resumo = {
        "formato": plano.formato,
        "mascara": plano.mascara,
        "total": len(plano.contas),
        "analiticas": analiticas,
        "sinteticas": len(plano.contas) - analiticas,
        "novas": novas,
        "alteradas": alteradas,
        "reativadas": reativadas,
        "removidas": len(removidas),
    }
    importacao = Importacao(
        empresa_id=empresa.id,
        tipo="PLANO",
        arquivo_id=arquivo.id if arquivo else None,
        usuario_id=usuario.id if usuario else None,
        resumo=resumo,
        avisos=[asdict(a) for a in avisos],
    )
    sessao.add(importacao)
    registrar_evento(sessao, "IMPORTAR_PLANO", detalhe=f"{empresa.nome}: {descrever_resumo(resumo)}")
    return importacao


def _milhar(numero: int) -> str:
    return f"{numero:,}".replace(",", ".")


def descrever_resumo(resumo: dict[str, Any]) -> str:
    partes = [f"{_milhar(resumo['total'])} contas ({_milhar(resumo['analiticas'])} analíticas)"]
    if resumo["novas"] and resumo["novas"] != resumo["total"]:
        partes.append(f"{resumo['novas']} novas")
    for chave, nome in (
        ("alteradas", "alteradas"),
        ("reativadas", "reativadas"),
        ("removidas", "desativadas"),
    ):
        if resumo.get(chave):
            partes.append(f"{resumo[chave]} {nome}")
    return ", ".join(partes)


# ---------------------------------------------------------------- consultas para as telas


def contar_contas(sessao: Session, empresa: Empresa) -> tuple[int, int]:
    """(total de contas ativas, analíticas)."""
    total, analiticas = sessao.execute(
        select(func.count(), func.count().filter(ContaContabil.tipo == "A")).where(
            ContaContabil.empresa_id == empresa.id, ContaContabil.ativa
        )
    ).one()
    return total, analiticas


def ultima_importacao(sessao: Session, empresa: Empresa) -> Importacao | None:
    return sessao.scalar(
        select(Importacao)
        .where(Importacao.empresa_id == empresa.id, Importacao.tipo == "PLANO")
        .order_by(Importacao.id.desc())
        .limit(1)
    )


def buscar_contas(
    sessao: Session, empresa: Empresa, texto: str = "", so_analiticas: bool = False, limite: int = 300
) -> tuple[list[ContaContabil], int]:
    """Busca por reduzido, classificação (com ou sem pontos) ou descrição sem ligar para acentos."""
    filtro = [ContaContabil.empresa_id == empresa.id, ContaContabil.ativa]
    if so_analiticas:
        filtro.append(ContaContabil.tipo == "A")
    texto = texto.strip()
    if texto:
        condicoes = [func.unaccent(ContaContabil.descricao).ilike(func.unaccent(f"%{texto}%"))]
        digitos = re.sub(r"\D", "", texto)
        if digitos and re.fullmatch(r"[\d.\s-]+", texto):
            condicoes += [
                cast(ContaContabil.reduzido, String) == digitos,
                ContaContabil.classificacao.startswith(digitos),
            ]
        filtro.append(or_(*condicoes))
    total = sessao.scalar(select(func.count()).select_from(ContaContabil).where(*filtro))
    contas = sessao.scalars(
        select(ContaContabil)
        .where(*filtro)
        .order_by(ContaContabil.classificacao, ContaContabil.reduzido)
        .limit(limite)
    )
    return list(contas), total


def empresas_com_plano(sessao: Session, exceto: Empresa) -> list[Empresa]:
    com_plano = select(ContaContabil.empresa_id).where(ContaContabil.ativa).distinct()
    return list(
        sessao.scalars(
            select(Empresa)
            .where(Empresa.id.in_(com_plano), Empresa.id != exceto.id)
            .order_by(Empresa.codigo_dominio)
        )
    )
