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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.modelos import (
    ContaChave,
    ContaContabil,
    Empresa,
    LancamentoHistorico,
    MovimentoExtrato,
    Padrao,
    Sugestao,
)
from app.servicos.aprendizado import CNPJ_NO_TEXTO, natureza_para_exibir, normalizar_natureza, normalizar_nome
from app.servicos.complemento import MODELO_PADRAO, montar_complemento
from app.servicos.contas_chave import nome_do_tipo, normalizar
from app.servicos.contas_permitidas import FiltroContas, carregar_filtro
from app.servicos.documentos import formatar_documento, normalizar_documento, tipo_documento

PROTEGIDAS = ("USUARIO",)  # origem que a classificação automática nunca troca

REGRAS_BANCO = (
    ("RENDIMENTO", "ENTRADA", re.compile(r"\bJUROS\b|REAJUSTE MONETARIO|RENDIMENTO|REMUNERACAO BASICA")),
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
# aplicação/resgate automático entre a conta corrente e a poupança/aplicação da própria empresa: o dinheiro não sai
# da empresa — nunca é receita nem despesa (o “BB Rende Fácil” é dentro da própria conta corrente)
_APLICACAO_AUTOMATICA = re.compile(
    r"RENDE FACIL|APLICACAO AUTOMATICA|RESGATE AUTOMATICO|APLICACAO POUPANCA|RESGATE POUPANCA|CURTO PRAZO AUTOMATIC"
)
FOLGA_APLICACAO = 3  # a poupança registra o resgate/aplicação automático até 3 dias depois da conta corrente
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
    documento: str = ""  # nº da nota/recibo (vem do demonstrativo); vazio = S/N


@dataclass
class Contexto:
    empresa: Empresa
    contas: dict[int, ContaContabil]
    por_reduzido: dict[int, ContaContabil]
    chaves: dict[str, ContaChave]
    padroes: dict[str, list[Padrao]]
    movimentos_do_periodo: list[MovimentoExtrato]
    filtro: FiltroContas
    # natureza do histórico → contas onde foi lançada (“SALARIO MENSAL” → 7007…), para o demonstrativo
    naturezas: dict[tuple[str, str], Counter] = field(default_factory=dict)
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
                MovimentoExtrato.data.between(
                    min(datas) - timedelta(days=FOLGA_APLICACAO + 1), max(datas) + timedelta(days=FOLGA_APLICACAO + 1)
                ),
                MovimentoExtrato.desdobrado.is_(False),
            )
        )
    )
    filtro = carregar_filtro(sessao, empresa, list(contas.values()))
    contexto = Contexto(empresa, contas, {c.reduzido: c for c in contas.values()}, chaves, padroes, periodo, filtro)
    if any(m.linha_demonstrativo is not None for m in movimentos):
        naturezas: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for sentido, natureza, conta_id in sessao.execute(
            select(
                LancamentoHistorico.sentido, LancamentoHistorico.natureza, LancamentoHistorico.contrapartida_id
            ).where(
                LancamentoHistorico.empresa_id == empresa.id,
                LancamentoHistorico.contrapartida_id.is_not(None),
                LancamentoHistorico.natureza.is_not(None),
                LancamentoHistorico.sentido.in_(("SAIDA", "ENTRADA")),
            )
        ):
            if len(chave := chave_natureza(natureza)) >= 3:
                naturezas[(sentido, chave)][conta_id] += 1
        contexto.naturezas = dict(naturezas)
    return contexto


# ---------------------------------------------------------------- passos


def _texto(movimento: MovimentoExtrato) -> str:
    return normalizar(f"{movimento.historico} {movimento.complemento or ''}")


def aplicacao_automatica(movimento: MovimentoExtrato) -> bool:
    return bool(_APLICACAO_AUTOMATICA.search(_texto(movimento)))


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
    automatica = aplicacao_automatica(movimento)

    def serve(outro: MovimentoExtrato) -> bool:
        if (
            outro.conta_bancaria_id == movimento.conta_bancaria_id
            or outro.valor != movimento.valor
            or outro.sentido != oposto
            or outro.parte_de_id
            or outro.id in ctx.pares_usados
            or movimento.id in ctx.pares_usados
        ):
            return False
        dias = abs((outro.data - movimento.data).days)
        # resgate automático: a conta corrente registra no dia 03, a poupança no dia 04
        return dias == 0 or (automatica and aplicacao_automatica(outro) and dias <= FOLGA_APLICACAO)

    candidatos = [outro for outro in ctx.movimentos_do_periodo if serve(outro)]
    par = ctx.par_de.get(movimento.id) or min(
        candidatos, key=lambda o: (abs((o.data - movimento.data).days), o.data, o.ordem), default=None
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


def _na_unidade(ctx: Contexto, movimento: MovimentoExtrato, conta_id: int | None) -> int | None:
    """A conta que vale nesta creche/projeto (a de outra creche vira a mesma desta)."""
    conta = ctx.contas.get(conta_id) if conta_id else None
    ajustada, _ = ctx.filtro.ajustar(conta, ctx.banco(movimento))
    return ajustada.id if ajustada else conta_id


def _duvida_some_na_unidade(ctx: Contexto, movimento: MovimentoExtrato, padrao: Padrao) -> bool:
    """O favorecido foi lançado em contas de creches diferentes (SABESP: ÁGUA - CARMEM e ÁGUA - JANDIRA, num Diário
    da associação inteira): nesta creche todas viram a mesma conta — então não há dúvida."""
    contas = [ctx.por_reduzido.get(item["conta"]) for item in (padrao.detalhes or {}).get("contas", [])]
    if len(contas) < 2 or None in contas:
        return False
    return len({_na_unidade(ctx, movimento, conta.id) for conta in contas}) == 1


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
    if padrao.ambiguo and not _duvida_some_na_unidade(ctx, movimento, padrao):
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
    na_unidade = _na_unidade(ctx, movimento, padrao.conta_id)
    empatados = [n for n in notas if n[0] == nota and _na_unidade(ctx, movimento, n[5].conta_id) != na_unidade]
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


def chave_natureza(texto: str | None) -> str:
    """“MAT. DE LIMPEZA (SABÃO)” → “MAT LIMPEZA”; “SERVIÇOS CONTÁBEIS (AGOSTO)” → “SERVICOS CONTABEIS”."""
    return normalizar_natureza(re.sub(r"\([^)]*\)", " ", texto or ""))


def _por_natureza(ctx: Contexto, movimento: MovimentoExtrato, especificacao: str) -> Proposta | None:
    """O que foi pago (do demonstrativo) → a conta onde o histórico lança isso, já na conta desta creche."""
    chave = chave_natureza(especificacao)
    if len(chave) < 3:
        return None
    banco = ctx.banco(movimento)
    pontos: Counter = Counter()
    vezes_por_conta: Counter = Counter()
    for (sentido, outra), contas in ctx.naturezas.items():
        if sentido != movimento.sentido:
            continue
        if outra == chave:
            peso = 2
        elif min(len(outra), len(chave)) >= 5 and fuzz.token_set_ratio(outra, chave) >= 90:
            peso = 1
        else:
            continue
        for conta_id, vezes in contas.items():
            conta, _ = ctx.filtro.ajustar(ctx.contas.get(conta_id), banco)
            if conta is not None:
                pontos[conta.id] += vezes * peso
                vezes_por_conta[conta.id] += vezes
    if not pontos:
        return None
    conta_id, melhor = pontos.most_common(1)[0]
    parte = melhor / sum(pontos.values())
    conta, vezes = ctx.contas[conta_id], vezes_por_conta[conta_id]
    confianca = 95 if parte >= 0.9 else 90 if parte >= 0.75 else 70
    if vezes < 3:  # visto uma ou duas vezes no histórico: sugere, mas para conferir
        confianca = min(confianca, 75)
    return Proposta(
        conta,
        confianca,
        "DEMONSTRATIVO",
        f"“{especificacao}” é lançado em {conta.rotulo} no histórico ({vezes} vez(es), {round(parte * 100)}%).",
    )


def _pelo_demonstrativo(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    """A linha do banco tem a sua linha no demonstrativo: vale o que ele diz — quem recebeu, o que foi pago e o nº
    do documento — e a conta sai do histórico por essa natureza (ou pelo favorecido/CNPJ de verdade)."""
    linha = movimento.linha_demonstrativo
    if linha is None:
        return None
    proposta = _regra_do_escritorio(ctx, movimento) or _por_natureza(ctx, movimento, linha.especificacao)
    if proposta is None and (linha.nome or linha.cnpj_cpf):
        cnpj = formatar_documento(linha.cnpj_cpf) if linha.cnpj_cpf else ""
        virtual = SimpleNamespace(
            id=movimento.id,
            data=movimento.data,
            valor=movimento.valor,
            sentido=movimento.sentido,
            conta_bancaria=movimento.conta_bancaria,
            historico=linha.especificacao,
            complemento=" ".join(p for p in (linha.nome, cnpj) if p),
            documento="",
        )
        proposta = next((p for passo in (_por_cnpj, _por_nome, _por_palavra) if (p := passo(ctx, virtual))), None)
    if proposta is None:  # o banco também ajuda (o repasse da prefeitura, a tarifa)
        passos = (_regra_de_banco, _por_cnpj, _por_nome, _por_palavra, _por_valor)
        proposta = next((p for passo in passos if (p := passo(ctx, movimento)) is not None), None)
    if proposta is None:
        proposta = Proposta(
            None, 40, "DEMONSTRATIVO", "O histórico não tem conta para isto: escolha a conta (a IA também olha)."
        )
    if linha.favorecido:  # como o escritório escrevia: o favorecido do demonstrativo já traz o CNPJ
        proposta.favorecido, proposta.cnpj = linha.favorecido, ""
    proposta.natureza = linha.especificacao or proposta.natureza
    proposta.documento = linha.documento
    item = f" item {linha.item}" if linha.item else ""
    proposta.justificativa = (
        f"📋 Demonstrativo{item} ({linha.documento_tipo or 'sem documento'}): {proposta.justificativa}"
    )
    return proposta


def _aplicacao_sem_par(ctx: Contexto, movimento: MovimentoExtrato) -> Proposta | None:
    """Aplicação/resgate automático sem a outra ponta no sistema: nunca vira receita nem despesa (nem vai para a IA)."""
    if not aplicacao_automatica(movimento):
        return None
    if "RENDE FACIL" in _texto(movimento):
        return Proposta(
            None,
            95,
            "TRANSFERENCIA",
            "BB Rende Fácil: aplicação/resgate automático dentro da própria conta — o dinheiro continua no banco, "
            "não gera lançamento.",
            natureza="APLICACAO AUTOMATICA",
            status="IGNORADO",
        )
    return Proposta(
        None,
        50,
        "TRANSFERENCIA",
        "Aplicação/resgate automático entre contas da própria empresa, mas a outra ponta (poupança/aplicação) não "
        "está no sistema: envie o extrato dela ou escolha a conta.",
        favorecido=movimento.complemento or "",
        natureza="APLICACAO/RESGATE AUTOMATICO",
    )


PASSOS = (
    _pelo_demonstrativo,
    _transferencia,
    _regra_do_escritorio,
    _regra_de_banco,
    _por_cnpj,
    _por_nome,
    _por_palavra,
    _por_valor,
    _aplicacao_sem_par,
)


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
        "DOCUMENTO": proposta.documento or "S/N",
    }
    return montar_complemento(empresa.modelo_complemento or MODELO_PADRAO, valores)[:300]


def classificar(sessao: Session, empresa: Empresa, inicio: date, fim: date) -> ResultadoClassificacao:
    """Classifica os movimentos da empresa no período. Não mexe no que o usuário escolheu nem no exportado."""
    from app.servicos.demonstrativos import cruzar_periodo

    cruzar_periodo(sessao, empresa, inicio, fim)  # extrato novo: liga as linhas do demonstrativo que esperavam
    movimentos = list(
        sessao.scalars(
            select(MovimentoExtrato)
            .where(
                MovimentoExtrato.empresa_id == empresa.id,
                MovimentoExtrato.data.between(inicio, fim),
                MovimentoExtrato.desdobrado.is_(False),  # a linha do banco desdobrada vale pelas partes
            )
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
            forte = proposta is not None and (
                proposta.confianca >= empresa.limiar_aprovacao
                # aplicação/resgate automático: a IA nunca devia ter dado conta de receita ou despesa
                or (proposta.origem == "TRANSFERENCIA" and aplicacao_automatica(movimento))
            )
            if sugestao and sugestao.origem == "IA" and not forte:
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
    if proposta.debito_credito is None and proposta.status != "IGNORADO":
        # só as contas desta creche; associação lança na despesa, não na conta do fornecedor
        proposta.contrapartida, nota = ctx.filtro.ajustar(proposta.contrapartida, banco)
        if nota:
            proposta.justificativa = f"{proposta.justificativa} {nota}"
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
