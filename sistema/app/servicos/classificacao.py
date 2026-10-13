"""Classificação dos movimentos do extrato (§6.2, passos 1 a 5 e 7). A IA para o que sobrar é a etapa 2.7.

Ordem — o primeiro que resolver vale:
1. Transferência entre contas da própria empresa (as duas pontas nos extratos: mesmo dia e valor, sentidos
   opostos) e regras de banco com as contas-chave (rendimento, IR retido, tarifa, IOF).
2. CNPJ/CPF escrito no movimento = de um favorecido aprendido (o BB escreve só a raiz: “42.066.834 JULIANA…”).
3. Nome parecido com o de um favorecido aprendido — o banco corta e abrevia: “JAQUELINE A R SANTOS” é
   “JAQUELINE APARECIDA RODRIGUES SANTOS”, “ZERA ASSESSORIA EMPRESARIAL E” é “ZERA ASSESSORIA EMPRES CONTABIL”.
4. Palavra-chave aprendida. 5. Valor que se repete num só favorecido (boleto pago por intermediador: LYTEX 910,00
   = plano odontológico do SIEMACO).
Verde (≥ 90) já vem APROVADO; amarela (70–89) e vermelha (< 70) ficam PENDENTES para a revisão. O que o usuário
escolheu (origem USUARIO) e o que já foi exportado nunca é refeito.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.modelos import (
    ContaChave,
    ContaContabil,
    Empresa,
    MovimentoExtrato,
    Padrao,
    Sugestao,
)
from app.servicos.aprendizado import CNPJ_NO_TEXTO, natureza_para_exibir, normalizar_natureza, normalizar_nome
from app.servicos.complemento import MODELO_PADRAO, montar_complemento
from app.servicos.contas_chave import nome_do_tipo, normalizar
from app.servicos.documentos import formatar_documento, normalizar_documento, tipo_documento

PROTEGIDAS = ("USUARIO",)  # origem que a classificação automática nunca troca

REGRAS_BANCO = (
    ("RENDIMENTO", "ENTRADA", re.compile(r"\bJUROS\b|REAJUSTE MONETARIO|RENDIMENTO|REMUNERACAO BASICA|RENDE FACIL")),
    ("IR_RETIDO", "SAIDA", re.compile(r"IMPOSTO DE RENDA")),
    ("TARIFA", "SAIDA", re.compile(r"\bTARIFA|\bTAR\b|CESTA DE (SERVICOS|RELACIONAMENTO)|PACOTE DE SERVICOS")),
    ("IOF", "SAIDA", re.compile(r"\bIOF\b")),
)
NATUREZA_REGRA = {
    "RENDIMENTO": "RENDIMENTO DE APLICACAO",
    "IR_RETIDO": "IR SOBRE APLICACAO",
    "TARIFA": "TARIFA BANCARIA",
    "IOF": "IOF",
}
_TRANSFERENCIA = re.compile(r"POUP|APLICAC|RESGAT|TRANSF|TRANSFERIDO")
_RAIZ_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}\b")


# ---------------------------------------------------------------- nomes parecidos


def _casa(a: str, b: str) -> bool:
    """Duas palavras são a mesma: iguais, uma é o começo da outra (corte do banco) ou quase iguais (SOUSA/SOUZA)."""
    if a == b:
        return True
    if min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)):
        return True
    return min(len(a), len(b)) >= 5 and fuzz.ratio(a, b) >= 85


def semelhanca(texto_banco: str, nome: str) -> int:
    """0 a 100: quanto o texto do banco parece o nome aprendido. O primeiro nome tem de bater; as iniciais
    soltas e as ligações (“A R”, “DE”) somem na normalização; cada palavra do banco precisa existir no nome."""
    banco, padrao = normalizar_nome(texto_banco).split(), normalizar_nome(nome).split()
    if not banco or not padrao:
        return 0
    if banco == padrao:
        return 100
    if not _casa(banco[0], padrao[0]):
        return 0
    if len(banco) == 1:  # uma palavra só identifica pouco
        return 90 if len(banco[0]) >= 5 else 0
    casadas = sum(1 for palavra in banco if any(_casa(palavra, outra) for outra in padrao))
    return round(100 * casadas / len(banco))


# ---------------------------------------------------------------- contexto


@dataclass
class Proposta:
    contrapartida: ContaContabil | None
    confianca: int
    origem: str
    justificativa: str
    padrao: Padrao | None = None
    favorecido: str = ""
    cnpj: str = ""
    natureza: str = ""
    debito_credito: tuple[ContaContabil | None, ContaContabil | None] | None = None  # transferência: as duas
    status: str | None = None  # força o status (IGNORADO)
    par: MovimentoExtrato | None = None


@dataclass
class Contexto:
    empresa: Empresa
    contas: dict[int, ContaContabil]
    por_reduzido: dict[int, ContaContabil]
    chaves: dict[str, ContaChave]
    padroes: dict[str, list[Padrao]]
    movimentos_do_periodo: list[MovimentoExtrato]
    pares_usados: set[int] = field(default_factory=set)  # já pareados (aqui ou pelo usuário)
    par_de: dict[int, MovimentoExtrato] = field(default_factory=dict)  # a outra ponta, para as duas usarem

    def banco(self, movimento: MovimentoExtrato) -> ContaContabil | None:
        chave = movimento.conta_bancaria.conta_chave
        return self.contas.get(chave.conta_id) if chave and chave.conta_id else None


def _carregar(sessao: Session, empresa: Empresa, movimentos: list[MovimentoExtrato]) -> Contexto:
    contas = {c.id: c for c in sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id))}
    chaves = {
        c.tipo: c
        for c in sessao.scalars(
            select(ContaChave).where(ContaChave.empresa_id == empresa.id, ContaChave.referencia == "")
        )
    }
    padroes: dict[str, list[Padrao]] = defaultdict(list)
    for padrao in sessao.scalars(select(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.ativo)):
        padroes[padrao.tipo].append(padrao)
    datas = [m.data for m in movimentos]
    periodo = list(
        sessao.scalars(
            select(MovimentoExtrato).where(
                MovimentoExtrato.empresa_id == empresa.id,
                MovimentoExtrato.data.between(min(datas) - timedelta(days=1), max(datas) + timedelta(days=1)),
            )
        )
    )
    return Contexto(empresa, contas, {c.reduzido: c for c in contas.values()}, chaves, padroes, periodo)


# ---------------------------------------------------------------- passos


def _texto(movimento: MovimentoExtrato) -> str:
    return normalizar(f"{movimento.historico} {movimento.complemento or ''}")


def _da_empresa(movimento: MovimentoExtrato) -> bool:
    """O favorecido é a própria empresa (“CASA C E N S MONTE BERIC”, titular cortado)."""
    titular, favorecido = normalizar(movimento.conta_bancaria.titular), normalizar(movimento.complemento)
    return bool(
        titular and len(favorecido) >= 10 and (titular.startswith(favorecido) or favorecido.startswith(titular))
    )


def _transferencia(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    sinal = bool(_TRANSFERENCIA.search(_texto(movimento))) or _da_empresa(movimento)
    if not sinal:
        return None
    oposto = "ENTRADA" if movimento.sentido == "SAIDA" else "SAIDA"
    par = ctx.par_de.get(movimento.id) or next(
        (
            outro
            for outro in ctx.movimentos_do_periodo
            if outro.conta_bancaria_id != movimento.conta_bancaria_id
            and outro.data == movimento.data
            and outro.valor == movimento.valor
            and outro.sentido == oposto
            and outro.id not in ctx.pares_usados
            and movimento.id not in ctx.pares_usados
        ),
        None,
    )
    if par is None:
        if not _da_empresa(movimento):
            return None
        # a outra ponta não está no sistema (extrato não enviado ou conta fora do plano): a outra conta fica em branco
        banco = ctx.banco(movimento)
        explicito = bool(re.search(r"POUP|APLICAC|RESGAT", _texto(movimento)))
        return Proposta(
            None,
            90 if explicito else 70,
            "TRANSFERENCIA",
            "Transferência entre contas da própria empresa; a outra conta fica em branco (o extrato dela não está "
            "no sistema).",
            favorecido=movimento.complemento or "",
            natureza="TRANSFERENCIA ENTRE CONTAS",
            debito_credito=(None, banco) if movimento.sentido == "SAIDA" else (banco, None),
        )
    ctx.pares_usados.update({movimento.id, par.id})
    ctx.par_de[par.id] = movimento
    saida, entrada = (movimento, par) if movimento.sentido == "SAIDA" else (par, movimento)
    origem, destino = ctx.banco(saida), ctx.banco(entrada)
    rotulo = f"{saida.conta_bancaria.rotulo} → {entrada.conta_bancaria.rotulo}"
    base = {"favorecido": "TRANSFERENCIA ENTRE CONTAS", "natureza": "TRANSFERENCIA ENTRE CONTAS", "par": par}
    if (origem is None or destino is None) and movimento is entrada:
        return Proposta(
            None,
            98,
            "TRANSFERENCIA",
            f"Transferência entre contas da empresa ({rotulo}): lançada na saída da outra conta.",
            status="IGNORADO",
            **base,
        )
    if origem is None or destino is None:  # a conta que não existe no plano fica em branco (decisão do escritório)
        return Proposta(
            None,
            98,
            "TRANSFERENCIA",
            f"Transferência entre contas da empresa ({rotulo}).",
            debito_credito=(destino, origem),
            **base,
        )
    if origem.id == destino.id:
        return Proposta(
            origem,
            98,
            "TRANSFERENCIA",
            f"Transferência entre contas da empresa ({rotulo}) que caem na "
            f"mesma conta contábil {origem.rotulo}: não gera lançamento.",
            status="IGNORADO",
            **base,
        )
    if movimento is entrada:  # a transferência é lançada uma vez só, na saída
        return Proposta(
            None,
            98,
            "TRANSFERENCIA",
            f"Transferência entre contas da empresa ({rotulo}): lançada na saída da outra conta.",
            status="IGNORADO",
            **base,
        )
    return Proposta(
        None,
        98,
        "TRANSFERENCIA",
        f"Transferência entre contas da empresa ({rotulo}).",
        debito_credito=(destino, origem),
        **base,
    )


def _regra_de_banco(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    texto = _texto(movimento)
    for tipo, sentido, padrao in REGRAS_BANCO:
        if movimento.sentido != sentido or not padrao.search(texto):
            continue
        chave = ctx.chaves.get(tipo)
        conta = ctx.contas.get(chave.conta_id) if chave and chave.conta_id else None
        if conta is None:
            return Proposta(
                None,
                40,
                "REGRA",
                f"{nome_do_tipo(tipo)}: a conta-chave ainda não foi definida (aba Plano de Contas).",
                natureza=NATUREZA_REGRA[tipo],
            )
        confianca = 95 if chave.confianca >= 80 else 80
        return Proposta(
            conta,
            confianca,
            "REGRA",
            f"{nome_do_tipo(tipo)} (conta-chave).",
            favorecido=movimento.conta_bancaria.banco_nome.upper(),
            natureza=NATUREZA_REGRA[tipo],
        )
    return None


def _tipo_padrao(movimento: MovimentoExtrato) -> str:
    return "FORNECEDOR" if movimento.sentido == "SAIDA" else "CLIENTE"


def _conta_do_padrao(ctx: Contexto, padrao: Padrao, valor: Decimal) -> tuple[ContaContabil | None, str]:
    """Conta e natureza: pelo valor quando o favorecido usa contas diferentes por natureza (SIEMACO: 910,00 =
    plano odontológico); senão a conta atual dele."""
    for item in (padrao.detalhes or {}).get("por_natureza", {}).values():
        if f"{valor:.2f}" in item.get("valores", []):
            return ctx.por_reduzido.get(item["conta"]), item.get("natureza") or ""
    return ctx.contas.get(padrao.conta_id) if padrao.conta_id else None, natureza_para_exibir(padrao.natureza) or ""


def _proposta_do_padrao(ctx, movimento, padrao: Padrao, confianca: int, origem: str, motivo: str) -> Proposta:
    conta, natureza = _conta_do_padrao(ctx, padrao, movimento.valor)
    vezes = f"{padrao.ocorrencias} lançamento(s) no histórico"
    if conta is None:
        return Proposta(
            None,
            30,
            origem,
            f"{motivo}: {padrao.nome} ainda não tem conta — cadastre no Domínio (fornecedores a cadastrar).",
            padrao,
            padrao.nome,
            padrao.cnpj_cpf or "",
            natureza,
        )
    if padrao.ambiguo:
        confianca = min(confianca, 70)
        motivo += " (lançado em contas diferentes no histórico: confira)"
    return Proposta(
        conta,
        confianca,
        origem,
        f"{motivo}: {padrao.nome} – {vezes}.",
        padrao,
        padrao.nome,
        padrao.cnpj_cpf or "",
        natureza,
    )


def _por_cnpj(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    texto = f"{movimento.historico} {movimento.complemento or ''} {movimento.documento or ''}"
    inteiros = {normalizar_documento(m.group(0)) for m in CNPJ_NO_TEXTO.finditer(texto)}
    inteiros = {d for d in inteiros if tipo_documento(d)}
    raizes = {normalizar_documento(m.group(0)) for m in _RAIZ_CNPJ.finditer(texto)}
    for padrao in ctx.padroes[_tipo_padrao(movimento)]:
        if not padrao.cnpj_cpf:
            continue
        if padrao.cnpj_cpf in inteiros or (len(padrao.cnpj_cpf) == 14 and padrao.cnpj_cpf[:8] in raizes):
            return _proposta_do_padrao(ctx, movimento, padrao, 95, "CNPJ", "CNPJ igual ao do favorecido")
    return None


def _por_nome(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    texto = movimento.complemento or movimento.historico
    notas = []
    for padrao in ctx.padroes[_tipo_padrao(movimento)]:
        nota = max(semelhanca(texto, padrao.nome), semelhanca(texto, padrao.chave))
        if nota >= 75:
            exato = normalizar_nome(texto) in (normalizar_nome(padrao.nome), padrao.chave)
            valor = f"{movimento.valor:.2f}" in (padrao.detalhes or {}).get("valores", [])
            notas.append((nota, exato, valor, padrao.ultima_data or date.min, padrao.ocorrencias, padrao))
    if not notas:
        return None
    notas.sort(key=lambda n: n[:5], reverse=True)
    nota, _, valor_bate, quando, _, padrao = notas[0]
    empatados = [n for n in notas if n[0] == nota and n[5].conta_id != padrao.conta_id]
    # o mesmo nome em contas diferentes: vale o mais recente se a prática mudou (2025 → 2026); senão confira
    duvida = any(quando - n[3] < timedelta(days=60) for n in empatados)
    confianca = (95 if valor_bate else 92) if nota == 100 else (90 if nota >= 90 else 80)
    if duvida:
        confianca = min(confianca, 75)
    motivo = "Nome igual ao do favorecido" if nota == 100 else f"Nome parecido ({nota}%) com o do favorecido"
    return _proposta_do_padrao(ctx, movimento, padrao, confianca, "NOME", motivo)


def _por_palavra(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    texto = f" {normalizar_natureza(movimento.historico + ' ' + (movimento.complemento or ''))} "
    for padrao in sorted(ctx.padroes["PALAVRA"], key=lambda p: -len(p.chave)):
        if f" {padrao.chave} " in texto:
            return _proposta_do_padrao(ctx, movimento, padrao, 85, "PALAVRA", "Palavra-chave aprendida")
    return None


def _por_valor(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    valor = f"{movimento.valor:.2f}"
    candidatos = [p for p in ctx.padroes[_tipo_padrao(movimento)] if valor in (p.detalhes or {}).get("valores", [])]
    if len(candidatos) != 1:
        return None  # nenhum ou vários favorecidos com o mesmo valor: não dá para saber
    return _proposta_do_padrao(
        ctx, movimento, candidatos[0], 75, "VALOR", f"Valor R$ {valor.replace('.', ',')} se repete em"
    )


def _regra_do_escritorio(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    """Regra criada pelo escritório na tela (“contém TARIFA → 535”): vale antes do aprendizado e aprova sozinha."""
    from app.servicos.regras import combina

    for regra in sorted(ctx.padroes["REGRA"], key=lambda p: -len(p.chave)):
        conta = ctx.contas.get(regra.conta_id) if regra.conta_id else None
        if conta is not None and combina(regra, movimento):
            return Proposta(
                conta,
                97,
                "ESCRITORIO",
                f"Regra do escritório: “{regra.nome}” → {conta.rotulo}.",
                natureza=regra.natureza or "",
            )
    return None


PASSOS = (_transferencia, _regra_do_escritorio, _regra_de_banco, _por_cnpj, _por_nome, _por_palavra, _por_valor)


# ---------------------------------------------------------------- gravar


@dataclass
class ResultadoClassificacao:
    verdes: int = 0
    amarelas: int = 0
    vermelhas: int = 0
    sem_lancamento: int = 0

    def contar(self, sugestao: Sugestao) -> None:
        """Conta uma sugestão que ficou como estava (do usuário, da IA ou exportada)."""
        if sugestao.status == "IGNORADO":
            self.sem_lancamento += 1
        elif sugestao.status in ("APROVADO", "EXPORTADO"):
            self.verdes += 1
        elif sugestao.confianca >= 70:
            self.amarelas += 1
        else:
            self.vermelhas += 1

    def resumo(self) -> str:
        return (
            f"Classificação: {self.verdes} aprovado(s) automaticamente, {self.amarelas} para conferir, "
            f"{self.vermelhas} pendente(s)"
            + (f", {self.sem_lancamento} sem lançamento" if self.sem_lancamento else "")
            + "."
        )


def complemento_da_proposta(empresa: Empresa, proposta: Proposta, movimento: MovimentoExtrato) -> str:
    valores = {
        "FAVORECIDO": proposta.favorecido or movimento.complemento or movimento.historico,
        "CNPJ": formatar_documento(proposta.cnpj) if proposta.cnpj else "",
        # sem natureza achada, vale o que o cliente respondeu na planilha de perguntas
        "NATUREZA": proposta.natureza
        or ((movimento.sugestao.resposta_cliente or "").upper() if movimento.sugestao else ""),
        "DOCUMENTO": "S/N",
    }
    return montar_complemento(empresa.modelo_complemento or MODELO_PADRAO, valores)[:300]


def classificar(sessao: Session, empresa: Empresa, inicio: date, fim: date) -> ResultadoClassificacao:
    """Classifica os movimentos da empresa no período. Não mexe no que o usuário escolheu nem no exportado."""
    movimentos = list(
        sessao.scalars(
            select(MovimentoExtrato)
            .where(MovimentoExtrato.empresa_id == empresa.id, MovimentoExtrato.data.between(inicio, fim))
            .order_by(MovimentoExtrato.data, MovimentoExtrato.conta_bancaria_id, MovimentoExtrato.ordem)
        )
    )
    resultado = ResultadoClassificacao()
    if not movimentos:
        return resultado
    ctx = _carregar(sessao, empresa, movimentos)
    for movimento in movimentos:  # pares já decididos pelo usuário não entram no pareamento automático
        if movimento.sugestao and movimento.sugestao.origem in PROTEGIDAS and movimento.sugestao.par_id:
            ctx.pares_usados.update({movimento.id, movimento.sugestao.par_id})
    sessao.info["auditoria_em_bloco"] = True  # um evento no log, não uma linha por sugestão
    try:
        for movimento in movimentos:
            sugestao = movimento.sugestao
            if sugestao and (
                sugestao.origem in PROTEGIDAS
                or sugestao.status == "EXPORTADO"
                or sugestao.conferido_por_id
                or sugestao.fornecedor_id  # espera (ou já recebeu) a conta do fornecedor a cadastrar
            ):
                resultado.contar(sugestao)
                continue
            proposta = next((p for passo in PASSOS if (p := passo(ctx, movimento)) is not None), None)
            if (
                sugestao
                and sugestao.origem == "IA"
                and (proposta is None or proposta.confianca < empresa.limiar_aprovacao)
            ):
                resultado.contar(sugestao)  # a resposta da IA vale até uma regra achar algo certo
                continue
            if proposta is None:
                proposta = Proposta(
                    None,
                    0,
                    "PENDENTE",
                    "Nenhuma regra nem favorecido aprendido reconheceu este movimento.",
                )
            _gravar(sessao, ctx, movimento, proposta, resultado)
        sessao.flush()
    finally:
        sessao.info.pop("auditoria_em_bloco", None)
    registrar_evento(
        sessao, "CLASSIFICAR", detalhe=f"{empresa.nome}, {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}: {resultado.resumo()}"
    )
    return resultado


def _gravar(sessao, ctx: Contexto, movimento: MovimentoExtrato, proposta: Proposta, resultado) -> None:
    banco = ctx.banco(movimento)
    if proposta.debito_credito is not None:
        debito, credito = proposta.debito_credito
    elif movimento.sentido == "SAIDA":
        debito, credito = proposta.contrapartida, banco
    else:
        debito, credito = banco, proposta.contrapartida
    justificativa = proposta.justificativa
    confianca = proposta.confianca
    if proposta.status != "IGNORADO":
        # conta de banco que não existe no plano (ex.: a poupança) fica EM BRANCO — decisão do escritório, completa
        # no Domínio; já a contrapartida que ninguém achou deixa a linha pendente
        transferencia = proposta.debito_credito is not None
        falta_contrapartida = not transferencia and proposta.contrapartida is None
        banco_em_branco = (debito is None or credito is None) if transferencia else banco is None
        if falta_contrapartida and confianca >= 70:
            confianca = 60
        if banco_em_branco:
            justificativa += (
                " Conta do banco em branco: ela não existe no plano de contas (complete no Domínio ou escolha "
                "nas contas-chave)."
            )
    if proposta.status == "IGNORADO":
        status = "IGNORADO"
        resultado.sem_lancamento += 1
    elif confianca >= ctx.empresa.limiar_aprovacao:
        status = "APROVADO"
        resultado.verdes += 1
    else:
        status = "PENDENTE"
        if confianca >= 70:
            resultado.amarelas += 1
        else:
            resultado.vermelhas += 1

    sugestao = movimento.sugestao
    if sugestao is None:
        sugestao = Sugestao(empresa_id=ctx.empresa.id)
        sessao.add(sugestao)  # primeiro na sessão, depois ligada ao movimento
        sugestao.movimento = movimento
    ignorado = proposta.status == "IGNORADO"
    if (sugestao.conta_debito, sugestao.conta_credito, sugestao.origem) != (debito, credito, proposta.origem):
        sugestao.revisado_ia = False  # a sugestão mudou: a IA pode olhar de novo
    sugestao.conta_debito = None if ignorado else debito
    sugestao.conta_credito = None if ignorado else credito
    sugestao.complemento = (
        complemento_da_proposta(ctx.empresa, proposta, movimento) if proposta.status != "IGNORADO" else ""
    )
    sugestao.confianca = confianca
    sugestao.origem = proposta.origem
    sugestao.justificativa = justificativa
    sugestao.padrao_id = proposta.padrao.id if proposta.padrao else None
    sugestao.par_id = proposta.par.id if proposta.par else None
    sugestao.status = status
