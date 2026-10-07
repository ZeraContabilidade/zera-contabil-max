"""Aprendizado com os lançamentos que o escritório já fez (§3.3, §6.1).

Fonte hoje: lanctos.txt antigos (§11.5). O Diário/Razão (etapa 1.7) entra pelo mesmo caminho:
cada linha vira um LancamentoHistorico e `aprender` recalcula os padrões da empresa.

- Favorecido → conta: vale o uso MAIS RECENTE (em 2025 os salários iam para a 331; em 2026, para a 187).
- Mesmo favorecido em contas diferentes explicadas pela natureza (sindicato: contribuição, mensalidade,
  plano odontológico) não é ambíguo: guarda a conta e os valores de cada natureza.
- Ambíguo = contas diferentes sem explicação → o usuário escolhe.
- Palavra-chave = natureza usada por vários favorecidos sempre na mesma conta (“SALARIO MENSAL” → 187).
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import chamar_ia
from app.modelos import (
    ContaChave,
    ContaContabil,
    Empresa,
    Importacao,
    LancamentoHistorico,
    Padrao,
    Usuario,
)
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.contas_chave import (
    TIPOS_BANCARIOS,
    Sugestao,
    gravar_sugestao,
    identificar_banco,
    naturezas,
    normalizar,
    referencia_bancaria,
)
from app.servicos.documentos import formatar_documento, normalizar_documento, tipo_documento
from app.servicos.lanctos import ler_lanctos, parece_lanctos
from app.servicos.plano import Aviso, ErroLeitura, decodificar

# ---------------------------------------------------------------- textos

_LIGACOES = {"DE", "DA", "DO", "DOS", "DAS", "E"}
_SUFIXOS = {"LTDA", "ME", "EPP", "EIRELI", "SA", "MEI", "CIA", "SS"}
_MESES = {
    "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO",
    "NOVEMBRO", "DEZEMBRO", "JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ",
}  # fmt: skip
CNPJ_NO_TEXTO = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{3,4}\s*-?\s*\d{2}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


def normalizar_nome(texto: str | None) -> str:
    """'DANIELA CORDEIRO DE OLIVEIRA' e 'Daniela Cordeiro Oliveira' → 'DANIELA CORDEIRO OLIVEIRA'."""
    palavras = re.sub(r"[^A-Z0-9 ]", " ", normalizar(texto)).split()
    return " ".join(p for p in palavras if len(p) > 1 and not p.isdigit() and p not in _LIGACOES and p not in _SUFIXOS)[
        :200
    ]


def normalizar_natureza(texto: str | None) -> str:
    """'SALÁRIO MENSAL REF JANEIRO' → 'SALARIO MENSAL'; 'SERVIÇOS CONTABEIS (JUNHO)' → 'SERVICOS CONTABEIS'."""
    texto = re.sub(r"\bREF\b.*$", "", normalizar(texto))
    palavras = re.sub(r"[^A-Z0-9 ]", " ", texto).split()
    return " ".join(
        p for p in palavras if len(p) > 1 and not any(c.isdigit() for c in p) and p not in _LIGACOES | _MESES
    )[:200]


_MES_ENTRE_PARENTESES = re.compile(
    r"\s*\((?:JANEIRO|FEVEREIRO|MAR[CÇ]O|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO)[^)]*\)",
    re.IGNORECASE,
)


def natureza_para_exibir(texto: str | None) -> str | None:
    """'SERVIÇOS CONTABEIS (JUNHO)' → 'SERVIÇOS CONTABEIS'; 'SALÁRIO MENSAL REF JANEIRO' → 'SALÁRIO MENSAL'."""
    if not texto:
        return texto
    limpo = _MES_ENTRE_PARENTESES.sub("", re.sub(r"\s+REF\b.*$", "", texto, flags=re.IGNORECASE))
    return " ".join(limpo.split()) or texto


@dataclass
class Complemento:
    favorecido: str
    cnpj_cpf: str | None  # só quando o dígito confere
    natureza: str
    documento: str


def separar_complemento(texto: str) -> Complemento:
    """'SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N' → favorecido, CNPJ, natureza e documento."""
    partes = [parte.strip() for parte in texto.split(" - ")]
    documento = ""
    if len(partes) > 1 and re.fullmatch(r"S/?N|[\dA-Z./-]{1,30}", partes[-1].upper()):
        if re.search(r"\d|S/?N", partes[-1].upper()):
            documento = partes.pop()
    achados = [m.group(0) for m in CNPJ_NO_TEXTO.finditer(texto)]
    cnpj = next((normalizar_documento(a) for a in achados if tipo_documento(a)), None)
    limpas = [" ".join(CNPJ_NO_TEXTO.sub(" ", parte).split()).strip(" -") for parte in partes]
    limpas = [parte for parte in limpas if parte]
    return Complemento(
        favorecido=limpas[0] if limpas else "",
        cnpj_cpf=cnpj,
        natureza=" - ".join(limpas[1:]),
        documento=documento,
    )


# ---------------------------------------------------------------- contas de banco

_DISPONIVEL = re.compile(r"DISPONI|CAIXA E EQUIVALENTES")


def contas_de_banco(contas: list[ContaContabil], chaves: list[ContaChave]) -> set[int]:
    """Contas-chave bancárias + analíticas do grupo Disponível (caixa, bancos, aplicações)."""
    ids = {c.conta_id for c in chaves if c.tipo in TIPOS_BANCARIOS and c.conta_id}
    grupos = [c.classificacao for c in contas if not c.analitica and _DISPONIVEL.search(normalizar(c.descricao))]
    for conta in contas:
        if conta.analitica and any(conta.classificacao.startswith(g) for g in grupos):
            ids.add(conta.id)
    return ids


# ---------------------------------------------------------------- importação do histórico


def importar_historico(
    sessao: Session, empresa: Empresa, nome_arquivo: str, conteudo: bytes, usuario: Usuario | None
) -> Importacao:
    texto = decodificar(conteudo)
    if not parece_lanctos(texto):
        raise ErroLeitura(
            "Não reconheci o arquivo. Por enquanto o sistema aprende com o lanctos.txt (o arquivo que a "
            "planilha gera para o Domínio); o Diário e o Razão chegam na próxima etapa."
        )
    linhas, avisos = ler_lanctos(texto)
    contas = list(sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)))
    if not any(c.ativa for c in contas):
        raise ErroLeitura("Importe o plano de contas da empresa antes do histórico (aba 2 Plano de Contas).")
    codigos = Counter(linha.codigo_empresa for linha in linhas if linha.codigo_empresa)
    if codigos and empresa.codigo_dominio not in codigos:
        outro = codigos.most_common(1)[0][0]
        raise ErroLeitura(
            f"Este arquivo é da empresa de código {outro} no Domínio, e esta é a {empresa.codigo_dominio}. "
            "Confira se escolheu a empresa certa."
        )
    de_outra = [linha for linha in linhas if linha.codigo_empresa not in (None, empresa.codigo_dominio)]
    if de_outra:
        avisos.append(
            Aviso(
                f"{len(de_outra)} linha(s) de outra empresa foram ignoradas.",
                [f"Linha {linha.numero}: código {linha.codigo_empresa}" for linha in de_outra],
            )
        )
        linhas = [linha for linha in linhas if linha not in de_outra]

    por_reduzido = {c.reduzido: c for c in contas}
    chaves = list(sessao.scalars(select(ContaChave).where(ContaChave.empresa_id == empresa.id)))
    bancos = contas_de_banco(contas, chaves)
    # reforço: conta do ATIVO presente em metade das linhas é o banco (ex.: crédito 8 em todas)
    uso = Counter(r for linha in linhas for r in (linha.debito, linha.credito))
    natureza = naturezas(contas)
    for reduzido, vezes in uso.items():
        conta = por_reduzido.get(reduzido)
        if conta and vezes >= len(linhas) / 2 and natureza.get(conta.id) == "ATIVO":
            bancos.add(conta.id)

    arquivo = guardar_arquivo(sessao, empresa, "HISTORICO", nome_arquivo, conteudo, usuario)
    importacao = Importacao(
        empresa_id=empresa.id,
        tipo="HISTORICO",
        arquivo_id=arquivo.id,
        usuario_id=usuario.id if usuario else None,
    )
    sessao.add(importacao)
    sessao.flush()

    marcas = set(sessao.scalars(select(LancamentoHistorico.marca).where(LancamentoHistorico.empresa_id == empresa.id)))
    repeticoes: Counter[str] = Counter()
    novos, repetidos, sem_conta = [], 0, []
    for linha in linhas:
        debito, credito = por_reduzido.get(linha.debito), por_reduzido.get(linha.credito)
        if debito is None or credito is None:
            faltando = linha.debito if debito is None else linha.credito
            sem_conta.append(f"Linha {linha.numero}: conta {faltando} não existe no plano")
            continue
        base = f"{linha.data.isoformat()}|{linha.debito}|{linha.credito}|{linha.valor}|{normalizar(linha.complemento)}"
        repeticoes[base] += 1  # duas linhas iguais no mesmo arquivo são dois lançamentos
        marca = hashlib.sha256(f"{base}#{repeticoes[base]}".encode()).hexdigest()
        if marca in marcas:
            repetidos += 1
            continue
        marcas.add(marca)
        if credito.id in bancos and debito.id not in bancos:
            sentido, contrapartida = "SAIDA", debito
        elif debito.id in bancos and credito.id not in bancos:
            sentido, contrapartida = "ENTRADA", credito
        else:
            sentido, contrapartida = "OUTRO", None
        partes = separar_complemento(linha.complemento)
        novos.append(
            LancamentoHistorico(
                empresa_id=empresa.id,
                importacao_id=importacao.id,
                data=linha.data,
                conta_debito_id=debito.id,
                conta_credito_id=credito.id,
                valor=linha.valor,
                historico=linha.complemento,
                favorecido=partes.favorecido[:200] or None,
                cnpj_cpf=partes.cnpj_cpf,
                natureza=partes.natureza[:200] or None,
                documento=partes.documento[:60] or None,
                sentido=sentido,
                contrapartida_id=contrapartida.id if contrapartida else None,
                marca=marca,
            )
        )
    sessao.add_all(novos)
    if sem_conta:
        avisos.insert(
            0,
            Aviso(
                f"{len(sem_conta)} linha(s) com conta que não existe no plano ficaram de fora. "
                "Reimporte o plano se criou contas novas no Domínio.",
                sem_conta,
            ),
        )
    datas = [lancamento.data for lancamento in novos]
    importacao.resumo = {
        "formato": "lanctos.txt",
        "linhas": len(linhas),
        "novos": len(novos),
        "repetidos": repetidos,
        "de": min(datas).isoformat() if datas else None,
        "ate": max(datas).isoformat() if datas else None,
    }
    importacao.avisos = [asdict(aviso) for aviso in avisos]
    registrar_evento(
        sessao,
        "IMPORTAR_HISTORICO",
        detalhe=f"{empresa.nome}: {len(novos)} lançamentos novos, {repetidos} repetidos ignorados",
    )
    sessao.flush()
    _ligar_bancos_do_historico(sessao, empresa, bancos, contas)
    return importacao


def _ligar_bancos_do_historico(sessao: Session, empresa: Empresa, bancos: set[int], contas: list) -> None:
    """Conta usada como banco no histórico e com banco + número na descrição vira conta-chave bancária
    (“BCO BRASIL CC 72637-0” → BB conta 72637-0 → conta 8)."""
    uso = dict(
        sessao.execute(
            select(LancamentoHistorico.conta_credito_id, func.count())
            .where(LancamentoHistorico.empresa_id == empresa.id, LancamentoHistorico.sentido == "SAIDA")
            .group_by(LancamentoHistorico.conta_credito_id)
        ).all()
    )
    for conta_id, vezes in uso.items():
        conta = next((c for c in contas if c.id == conta_id), None)
        if conta is None or conta_id not in bancos:
            continue
        texto = normalizar(conta.descricao)
        banco = identificar_banco(texto)
        numero = re.search(r"\d[\d.]*-[\dXx]|\d{4,}", texto)
        if not banco or not numero:
            continue
        tipo = "POUPANCA" if "POUP" in texto else "APLICACAO" if "APLIC" in texto else "BANCO"
        gravar_sugestao(
            sessao,
            empresa,
            Sugestao(
                tipo,
                conta,
                "REGRA",
                90,
                f"Usada como banco em {vezes} pagamento(s) do histórico da empresa.",
                referencia_bancaria(banco, numero.group(0)),
            ),
        )


# ---------------------------------------------------------------- aprender


def _conta_atual(lancamentos: list[LancamentoHistorico]) -> tuple[int, float]:
    """(conta atual, quanto dela no uso recente). Uso recente estável (2+ seguidas) = mudança de prática."""
    ordenados = sorted(lancamentos, key=lambda lancamento: (lancamento.data, lancamento.id))
    ultima = ordenados[-1].contrapartida_id
    seguidas = 0
    for lancamento in reversed(ordenados):
        if lancamento.contrapartida_id != ultima:
            break
        seguidas += 1
    if seguidas >= 2 or len(ordenados) == 1:
        return ultima, 1.0
    recentes = ordenados[-5:]
    contagem = Counter(lancamento.contrapartida_id for lancamento in recentes)
    ultima_vez = {lancamento.contrapartida_id: lancamento.data for lancamento in recentes}
    melhor = max(contagem, key=lambda conta: (contagem[conta], ultima_vez[conta]))
    return melhor, contagem[melhor] / len(recentes)


def _valores_recorrentes(lancamentos: list[LancamentoHistorico]) -> list[str]:
    """Valores que aparecem 2+ vezes, o mais recente primeiro (o salário atual antes do antigo)."""
    contagem = Counter(lancamento.valor for lancamento in lancamentos)
    ultima = {}
    for lancamento in lancamentos:
        ultima[lancamento.valor] = max(lancamento.data, ultima.get(lancamento.valor, lancamento.data))
    repetidos = [valor for valor, vezes in contagem.items() if vezes >= 2]
    return [str(v) for v in sorted(repetidos, key=lambda v: (ultima[v], contagem[v]), reverse=True)[:5]]


def _mais_recente(lancamentos, atributo: str):
    for lancamento in sorted(lancamentos, key=lambda item: (item.data, item.id), reverse=True):
        if valor := getattr(lancamento, atributo):
            return valor
    return None


def _resumir(lancamentos: list[LancamentoHistorico], reduzido: dict[int, int]) -> dict[str, Any]:
    conta_id, parte = _conta_atual(lancamentos)
    por_natureza = {}
    grupos = defaultdict(list)
    for lancamento in lancamentos:
        if chave := normalizar_natureza(lancamento.natureza):
            grupos[chave].append(lancamento)
    for chave, itens in grupos.items():
        conta_natureza, parte_natureza = _conta_atual(itens)
        por_natureza[chave] = {
            "natureza": natureza_para_exibir(_mais_recente(itens, "natureza")),
            "conta": reduzido[conta_natureza],
            "ocorrencias": len(itens),
            "firme": parte_natureza >= 0.7,
            "valores": _valores_recorrentes(itens),
        }
    contas_naturezas = {item["conta"] for item in por_natureza.values()}
    explicado = len(por_natureza) > 1 and len(contas_naturezas) > 1 and all(i["firme"] for i in por_natureza.values())
    contas = Counter(lancamento.contrapartida_id for lancamento in lancamentos)
    ultima_por_conta = {}
    for lancamento in lancamentos:
        anterior = ultima_por_conta.get(lancamento.contrapartida_id)
        ultima_por_conta[lancamento.contrapartida_id] = max(lancamento.data, anterior or lancamento.data)
    return {
        "conta_id": conta_id,
        "ambiguo": parte < 0.7 and not explicado,
        "natureza": natureza_para_exibir(_mais_recente(lancamentos, "natureza")),
        "ocorrencias": len(lancamentos),
        "total": sum((lancamento.valor for lancamento in lancamentos), Decimal("0")),
        "ultima_data": max(lancamento.data for lancamento in lancamentos),
        "detalhes": {
            "contas": [
                {"conta": reduzido[c], "ocorrencias": n, "ultima": ultima_por_conta[c].isoformat()}
                for c, n in contas.most_common()
            ],
            "por_natureza": por_natureza if len(por_natureza) > 1 else {},
            "valores": _valores_recorrentes(lancamentos),
        },
    }


@dataclass
class ResultadoAprendizado:
    fornecedores: int = 0
    clientes: int = 0
    palavras: int = 0
    ambiguos: int = 0

    def resumo(self) -> str:
        texto = (
            f"🤖 Aprendido: {self.fornecedores} fornecedor(es)/favorecido(s), {self.clientes} cliente(s) "
            f"e {self.palavras} palavra(s)-chave."
        )
        if self.ambiguos:
            texto += f" {self.ambiguos} ficaram ambíguos: escolha a conta na aba Aprendizado."
        return texto


def aprender(sessao: Session, empresa: Empresa) -> ResultadoAprendizado:
    """Recalcula os padrões a partir de TODO o histórico da empresa. A escolha do usuário é mantida."""
    lancamentos = list(
        sessao.scalars(
            select(LancamentoHistorico).where(
                LancamentoHistorico.empresa_id == empresa.id,
                LancamentoHistorico.contrapartida_id.is_not(None),
                LancamentoHistorico.sentido.in_(("SAIDA", "ENTRADA")),
            )
        )
    )
    reduzido = dict(
        sessao.execute(
            select(ContaContabil.id, ContaContabil.reduzido).where(ContaContabil.empresa_id == empresa.id)
        ).all()
    )
    existentes = {(p.tipo, p.chave): p for p in sessao.scalars(select(Padrao).where(Padrao.empresa_id == empresa.id))}

    # favorecidos: agrupados pelo nome normalizado; nomes diferentes com o mesmo CNPJ viram um só
    por_nome = defaultdict(list)
    for lancamento in lancamentos:
        tipo = "FORNECEDOR" if lancamento.sentido == "SAIDA" else "CLIENTE"
        if chave := normalizar_nome(lancamento.favorecido):
            por_nome[(tipo, chave)].append(lancamento)
    grupos, dono_do_cnpj = defaultdict(list), {}
    for (tipo, chave), itens in sorted(por_nome.items(), key=lambda item: (-len(item[1]), item[0])):
        cnpjs = {lancamento.cnpj_cpf for lancamento in itens if lancamento.cnpj_cpf}
        alvo = next((dono_do_cnpj[(tipo, c)] for c in cnpjs if (tipo, c) in dono_do_cnpj), (tipo, chave))
        grupos[alvo].extend(itens)
        for cnpj in cnpjs:
            dono_do_cnpj.setdefault((tipo, cnpj), alvo)

    # palavras-chave: natureza usada por 2+ favorecidos sempre na mesma conta
    por_natureza = defaultdict(list)
    for lancamento in lancamentos:
        if len(chave := normalizar_natureza(lancamento.natureza)) >= 4:
            por_natureza[chave].append(lancamento)

    resultado = ResultadoAprendizado()
    produzidos = set(grupos)
    sessao.info["auditoria_em_bloco"] = True  # um evento no log, não uma linha por padrão
    try:
        for (tipo, chave), itens in grupos.items():
            dados = _resumir(itens, reduzido)
            dados["nome"] = _mais_recente(itens, "favorecido")
            dados["cnpj_cpf"] = _mais_recente(itens, "cnpj_cpf")
            padrao = _gravar_padrao(sessao, empresa, existentes, tipo, chave, dados)
            resultado.fornecedores += tipo == "FORNECEDOR"
            resultado.clientes += tipo == "CLIENTE"
            resultado.ambiguos += padrao.ambiguo and padrao.ativo
        for chave, itens in por_natureza.items():
            favorecidos = {normalizar_nome(lancamento.favorecido) for lancamento in itens}
            conta_id, parte = _conta_atual(itens)
            if len(favorecidos) < 2 or parte < 0.7:
                continue
            dados = _resumir(itens, reduzido)
            nome = natureza_para_exibir(_mais_recente(itens, "natureza"))
            dados.update(nome=nome, cnpj_cpf=None, conta_id=conta_id, ambiguo=False)
            _gravar_padrao(sessao, empresa, existentes, "PALAVRA", chave, dados)
            produzidos.add(("PALAVRA", chave))
            resultado.palavras += 1
        # padrão aprendido que o histórico não sustenta mais (ex.: dois nomes do mesmo CNPJ que viraram um só)
        # sai; o que o usuário escolheu à mão fica
        for chave, padrao in existentes.items():
            if chave not in produzidos and padrao.origem == "APRENDIDO":
                sessao.delete(padrao)
        sessao.flush()
    finally:
        sessao.info.pop("auditoria_em_bloco", None)
    registrar_evento(sessao, "APRENDER", detalhe=f"{empresa.nome}: {resultado.resumo()}")
    return resultado


def _gravar_padrao(sessao, empresa, existentes, tipo: str, chave: str, dados: dict[str, Any]) -> Padrao:
    padrao = existentes.get((tipo, chave))
    if padrao is None:
        padrao = Padrao(empresa_id=empresa.id, tipo=tipo, chave=chave, ativo=True, origem="APRENDIDO")
        sessao.add(padrao)
        existentes[(tipo, chave)] = padrao
    padrao.nome = (dados["nome"] or chave)[:200]
    padrao.cnpj_cpf = dados["cnpj_cpf"]
    padrao.natureza = (dados["natureza"] or "")[:200] or None
    padrao.ocorrencias = dados["ocorrencias"]
    padrao.total = dados["total"]
    padrao.ultima_data = dados["ultima_data"]
    padrao.detalhes = dados["detalhes"]
    if padrao.origem != "USUARIO":  # a escolha do usuário vale mais que o aprendido
        padrao.conta_id = dados["conta_id"]
        padrao.ambiguo = dados["ambiguo"]
    return padrao


# ---------------------------------------------------------------- consultas e ações das telas


def resumo_historico(sessao: Session, empresa: Empresa) -> dict[str, Any]:
    total, inicio, fim = sessao.execute(
        select(func.count(), func.min(LancamentoHistorico.data), func.max(LancamentoHistorico.data)).where(
            LancamentoHistorico.empresa_id == empresa.id
        )
    ).one()
    contagem = dict(
        sessao.execute(
            select(Padrao.tipo, func.count()).where(Padrao.empresa_id == empresa.id, Padrao.ativo).group_by(Padrao.tipo)
        ).all()
    )
    ambiguos = sessao.scalar(
        select(func.count()).select_from(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.ambiguo, Padrao.ativo)
    )
    return {"lancamentos": total, "de": inicio, "ate": fim, "padroes": contagem, "ambiguos": ambiguos}


def listar_padroes(
    sessao: Session, empresa: Empresa, tipo: str, texto: str = "", so_ambiguos: bool = False
) -> list[Padrao]:
    consulta = select(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.tipo == tipo)
    if so_ambiguos:
        consulta = consulta.where(Padrao.ambiguo, Padrao.ativo)
    if texto := texto.strip():
        documento = normalizar_documento(texto)
        condicao = func.unaccent(Padrao.nome).ilike(func.unaccent(f"%{texto}%"))
        if documento:
            condicao = condicao | Padrao.cnpj_cpf.like(f"%{documento}%")
        consulta = consulta.where(condicao)
    ordem = (Padrao.ativo.desc(), Padrao.ambiguo.desc(), Padrao.ocorrencias.desc(), Padrao.nome)
    return list(sessao.scalars(consulta.order_by(*ordem)))


def despesas_por_conta(sessao: Session, empresa: Empresa) -> list[tuple[ContaContabil, int, Decimal]]:
    """Resumo para conferência (§3.3): quanto foi pago em cada conta, pelo histórico."""
    return list(
        sessao.execute(
            select(ContaContabil, func.count(), func.sum(LancamentoHistorico.valor))
            .join(LancamentoHistorico, LancamentoHistorico.contrapartida_id == ContaContabil.id)
            .where(LancamentoHistorico.empresa_id == empresa.id, LancamentoHistorico.sentido == "SAIDA")
            .group_by(ContaContabil.id)
            .order_by(func.sum(LancamentoHistorico.valor).desc())
        ).all()
    )


def documento_formatado(padrao: Padrao) -> str:
    return formatar_documento(padrao.cnpj_cpf) if padrao.cnpj_cpf else ""


# ---------------------------------------------------------------- perfil da empresa (IA)

INSTRUCOES_PERFIL = """Você é contador(a) do escritório Zera Contabilidade. Escreva o PERFIL de uma \
empresa-cliente para orientar a classificação automática dos extratos bancários dela: atividade, \
principais fornecedores e despesas típicas, e como os pagamentos costumam ser lançados (direto em \
despesa ou baixando contas do passivo, como salários a pagar). No máximo 120 palavras, em português, \
frases curtas, sem inventar nada que não esteja nos dados."""


def gerar_perfil(sessao: Session, empresa: Empresa, usuario: Usuario | None = None) -> str:
    fornecedores = listar_padroes(sessao, empresa, "FORNECEDOR")[:20]
    contas = despesas_por_conta(sessao, empresa)[:12]
    publicos = empresa.dados_publicos or {}
    linhas = [
        f"Empresa: {empresa.nome}; regime: {empresa.regime.rotulo if empresa.regime else 'não informado'}; "
        f"natureza jurídica: {publicos.get('natureza_juridica', '-')}; atividade: {publicos.get('atividade', '-')}.",
        "Principais favorecidos (nome | conta | natureza | vezes):",
        *(
            f"- {p.nome} | {p.conta.rotulo if p.conta else '-'} | {p.natureza or '-'} | {p.ocorrencias}"
            for p in fornecedores
        ),
        "Pagamentos por conta (conta | lançamentos | total R$):",
        *(f"- {conta.rotulo} | {vezes} | {total}" for conta, vezes, total in contas),
    ]
    pedido = PedidoIA(
        finalidade="perfil_empresa",
        instrucoes=INSTRUCOES_PERFIL,
        pergunta="\n".join(linhas),
        esquema={
            "type": "object",
            "properties": {"perfil": {"type": "string"}},
            "required": ["perfil"],
            "additionalProperties": False,
        },
        max_tokens=1500,
    )
    resposta = chamar_ia(sessao, pedido, empresa, usuario)
    perfil = str(resposta.dados.get("perfil") or "").strip()
    if not perfil:
        raise ErroIA("A IA não escreveu o perfil. Tente de novo.")
    empresa.perfil_ia = perfil[:2000]
    empresa.perfil_ia_em = datetime.now(UTC)
    return empresa.perfil_ia
