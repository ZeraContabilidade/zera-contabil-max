"""IA no que a classificação por regras não resolveu (§6.2, passo 6): automático, sem botão, em lotes.

Vão para a IA as sugestões pendentes e as amarelas (confiança < 90) cuja conta do banco é conhecida e que não
vieram do usuário, de uma transferência entre contas ou da própria IA. A IA recebe, num contexto estável
(cache): o plano de contas analítico, as contas que a empresa mais usa no histórico (com exemplos), os
favorecidos aprendidos, as contas-chave e o perfil da empresa; e devolve só a CONTRAPARTIDA (o lado do banco o
sistema já sabe). Toda resposta é conferida: a conta tem de existir no plano, ser analítica e não ser a do banco.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import IAIndisponivel, chamar_ia
from app.modelos import (
    ContaChave,
    ContaContabil,
    Empresa,
    LancamentoHistorico,
    MovimentoExtrato,
    Padrao,
    Sugestao,
    Usuario,
)
from app.servicos.classificacao import LIMIAR_APROVACAO, Proposta, complemento_da_proposta
from app.servicos.contas_chave import naturezas, nome_do_tipo

TAMANHO_LOTE = 40
MAXIMO_DE_LOTES = 5  # por vez (200 linhas); o resto fica para o próximo “Classificar de novo”
NAO_PERGUNTAR = ("USUARIO", "IA", "TRANSFERENCIA")

INSTRUCOES = """Você é contador(a) do escritório Zera Contabilidade e classifica movimentos de extrato bancário \
de uma empresa-cliente para o Sistema Domínio. Para cada linha, o lado do BANCO já é conhecido: escolha só a \
CONTRAPARTIDA — a conta do plano onde o pagamento (saída) ou o recebimento (entrada) deve ser lançado.

Regras:
- Use SOMENTE contas analíticas do plano de contas abaixo (pelo código reduzido). Nunca invente conta.
- Siga a prática da empresa: o histórico mostra onde ela costuma lançar (ex.: salário pago por transferência vai \
para “salários a pagar”, guia de FGTS para “FGTS a recolher”, DARF de INSS/IRRF da folha para as contas a recolher, \
repasse de prefeitura para a conta onde os repasses são recebidos).
- favorecido: quem recebeu ou pagou, como o banco escreveu ou como aparece nos favorecidos aprendidos.
- natureza: o que foi pago ou recebido, curto, em maiúsculas (ex.: SALARIO MENSAL, MATERIAL DE LIMPEZA, \
REPASSE MUNICIPAL).
- confianca de 0 a 100: 90+ só quando o histórico da empresa mostra claramente essa conta para esse tipo de \
movimento; 70–89 quando é provável; abaixo de 70 quando é palpite. Sem ideia: conta 0 e confiança 0.
- justificativa: uma frase curta em português dizendo por quê.
Responda um item para cada id recebido."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "conta": {"type": "integer"},
                    "favorecido": {"type": "string"},
                    "natureza": {"type": "string"},
                    "confianca": {"type": "integer"},
                    "justificativa": {"type": "string"},
                },
                "required": ["id", "conta", "favorecido", "natureza", "confianca", "justificativa"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["itens"],
    "additionalProperties": False,
}


def montar_contexto(sessao: Session, empresa: Empresa) -> str:
    """Bloco grande e estável (vai para o cache da IA): sempre na mesma ordem."""
    contas = list(sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)))
    natureza = naturezas(contas)
    por_id = {c.id: c for c in contas}
    linhas = [f"EMPRESA: {empresa.nome}"]
    if empresa.perfil_ia:
        linhas.append(f"PERFIL: {empresa.perfil_ia}")

    uso = sessao.execute(
        select(LancamentoHistorico.contrapartida_id, func.count())
        .where(
            LancamentoHistorico.empresa_id == empresa.id,
            LancamentoHistorico.sentido.in_(("SAIDA", "ENTRADA")),
            LancamentoHistorico.contrapartida_id.is_not(None),
        )
        .group_by(LancamentoHistorico.contrapartida_id)
        .order_by(func.count().desc())
        .limit(50)
    ).all()
    if uso:
        exemplos: dict[int, Counter] = defaultdict(Counter)
        for conta_id, favorecido in sessao.execute(
            select(LancamentoHistorico.contrapartida_id, LancamentoHistorico.favorecido).where(
                LancamentoHistorico.empresa_id == empresa.id, LancamentoHistorico.favorecido.is_not(None)
            )
        ):
            exemplos[conta_id][favorecido] += 1
        linhas.append("\nCONTAS QUE A EMPRESA MAIS USA NO HISTÓRICO (reduzido | descrição | vezes | exemplos):")
        for conta_id, vezes in uso:
            conta = por_id[conta_id]
            amostra = ", ".join(nome for nome, _ in exemplos[conta_id].most_common(4))
            linhas.append(f"{conta.reduzido} | {conta.descricao} | {vezes} | {amostra}")

    padroes = sessao.scalars(
        select(Padrao)
        .where(Padrao.empresa_id == empresa.id, Padrao.ativo, Padrao.conta_id.is_not(None))
        .order_by(Padrao.tipo, Padrao.ocorrencias.desc(), Padrao.chave)
        .limit(120)
    ).all()
    if padroes:
        linhas.append("\nFAVORECIDOS E PALAVRAS APRENDIDOS (tipo | nome | conta | natureza | valores que se repetem):")
        for p in padroes:
            valores = ", ".join((p.detalhes or {}).get("valores", [])[:3])
            linhas.append(f"{p.tipo} | {p.nome} | {por_id[p.conta_id].reduzido} | {p.natureza or '-'} | {valores}")

    chaves = sessao.scalars(
        select(ContaChave).where(ContaChave.empresa_id == empresa.id, ContaChave.conta_id.is_not(None))
    ).all()
    if chaves:
        linhas.append("\nCONTAS-CHAVE:")
        for chave in sorted(chaves, key=lambda c: (c.tipo, c.referencia)):
            rotulo = f"{nome_do_tipo(chave.tipo)} {chave.referencia}".strip()
            linhas.append(f"{rotulo} → {por_id[chave.conta_id].reduzido}")

    linhas.append("\nPLANO DE CONTAS ANALÍTICO (reduzido | classificação | descrição | natureza):")
    for conta in sorted((c for c in contas if c.analitica and c.ativa), key=lambda c: c.classificacao):
        linhas.append(
            f"{conta.reduzido} | {conta.classificacao_formatada} | {conta.descricao} | {natureza.get(conta.id, '-')}"
        )
    return "\n".join(linhas)


def candidatas(sessao: Session, empresa: Empresa, movimentos: list[MovimentoExtrato]) -> list[Sugestao]:
    """O que vale perguntar à IA: pendente ou amarela, com a conta do banco conhecida."""
    escolhidas = []
    for movimento in movimentos:
        sugestao = movimento.sugestao
        chave = movimento.conta_bancaria.conta_chave
        if (
            sugestao is not None
            and sugestao.status == "PENDENTE"
            and sugestao.confianca < LIMIAR_APROVACAO
            and sugestao.origem not in NAO_PERGUNTAR
            and not sugestao.revisado_ia
            and chave is not None
            and chave.conta_id is not None
        ):
            escolhidas.append(sugestao)
    return escolhidas


def _linha(numero: int, sugestao: Sugestao, contas: dict[int, ContaContabil]) -> str:
    m = sugestao.movimento
    banco = contas[m.conta_bancaria.conta_chave.conta_id]
    atual = ""
    if sugestao.confianca >= 70:  # amarela: mostra o que as regras acharam
        contrapartida = sugestao.conta_debito if m.sentido == "SAIDA" else sugestao.conta_credito
        if contrapartida:
            atual = f" | regras sugeriram {contrapartida.reduzido} ({sugestao.justificativa})"
    sentido = "SAÍDA (pagamento)" if m.sentido == "SAIDA" else "ENTRADA (recebimento)"
    return (
        f"{numero}. {m.data:%d/%m/%Y} | {sentido} | R$ {m.valor} | {m.historico} | {m.complemento or '-'} | "
        f"banco: {banco.reduzido} {banco.descricao}{atual}"
    )


@dataclass
class ResultadoIA:
    perguntadas: int = 0
    verdes: int = 0
    amarelas: int = 0
    vermelhas: int = 0
    recusadas: int = 0  # conta inexistente, sintética ou a do próprio banco
    aviso: str = ""

    def resumo(self) -> str:
        texto = (
            f"🤖 A IA olhou {self.perguntadas} movimento(s): {self.verdes} aprovado(s), {self.amarelas} para "
            f"conferir, {self.vermelhas} ainda pendente(s)"
        )
        if self.recusadas:
            texto += f" ({self.recusadas} resposta(s) com conta inválida foram descartadas)"
        return texto + "."


def classificar_com_ia(
    sessao: Session, empresa: Empresa, usuario: Usuario | None, inicio: date, fim: date
) -> ResultadoIA:
    """Pergunta à IA, em lotes, o que sobrou no período. IA desligada → IAIndisponivel (nada muda)."""
    resultado = ResultadoIA()
    movimentos = sessao.scalars(
        select(MovimentoExtrato)
        .where(MovimentoExtrato.empresa_id == empresa.id, MovimentoExtrato.data.between(inicio, fim))
        .order_by(MovimentoExtrato.data, MovimentoExtrato.conta_bancaria_id, MovimentoExtrato.ordem)
    ).all()
    sugestoes = candidatas(sessao, empresa, list(movimentos))
    if not sugestoes:
        return resultado
    contas = {c.id: c for c in sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id))}
    por_reduzido = {c.reduzido: c for c in contas.values()}
    contexto = montar_contexto(sessao, empresa)
    lotes = [sugestoes[i : i + TAMANHO_LOTE] for i in range(0, len(sugestoes), TAMANHO_LOTE)]
    sessao.info["auditoria_em_bloco"] = True
    try:
        for numero_lote, lote in enumerate(lotes[:MAXIMO_DE_LOTES]):
            pedido = PedidoIA(
                finalidade="classificacao",
                instrucoes=INSTRUCOES,
                contexto=contexto,
                pergunta="\n".join(_linha(i, s, contas) for i, s in enumerate(lote, 1)),
                esquema=ESQUEMA,
                max_tokens=8000,
            )
            try:
                resposta = chamar_ia(sessao, pedido, empresa, usuario)
            except IAIndisponivel as erro:
                if numero_lote == 0:
                    raise
                resultado.aviso = str(erro)
                break
            except ErroIA as erro:
                resultado.aviso = f"A IA não respondeu agora ({erro}). Clique em “Classificar de novo” mais tarde."
                break
            respostas = {item.get("id"): item for item in resposta.dados.get("itens", []) if isinstance(item, dict)}
            for i, sugestao in enumerate(lote, 1):
                if (item := respostas.get(i)) is not None:
                    resultado.perguntadas += 1
                    _aplicar(empresa, sugestao, item, contas, por_reduzido, resultado)
        sessao.flush()
    finally:
        sessao.info.pop("auditoria_em_bloco", None)
    return resultado


def _aplicar(empresa, sugestao: Sugestao, item: dict, contas, por_reduzido, resultado: ResultadoIA) -> None:
    movimento = sugestao.movimento
    banco = contas[movimento.conta_bancaria.conta_chave.conta_id]
    conta = por_reduzido.get(item.get("conta"))
    confianca = max(0, min(100, int(item.get("confianca") or 0)))
    justificativa = " ".join(str(item.get("justificativa") or "").split())[:300]
    sugestao.revisado_ia = True  # respondida (mesmo que não sirva): não pergunta de novo
    if conta is None or not conta.analitica or conta.id == banco.id:
        if item.get("conta"):
            resultado.recusadas += 1
        conta, confianca = None, 0
    if conta is None or confianca <= sugestao.confianca:
        # a IA não soube, respondeu conta inválida ou as regras já tinham algo igual ou melhor: fica como está
        resultado.amarelas += sugestao.confianca >= 70
        resultado.vermelhas += sugestao.confianca < 70
        if conta is None and sugestao.confianca < 70 and justificativa:
            sugestao.justificativa = f"{sugestao.justificativa} 🤖 A IA também não soube: {justificativa}"[:2000]
        return
    proposta = Proposta(
        conta,
        confianca,
        "IA",
        f"🤖 IA: {justificativa or 'sem justificativa'}",
        favorecido=" ".join(str(item.get("favorecido") or "").upper().split())[:200],
        natureza=" ".join(str(item.get("natureza") or "").upper().split())[:200],
    )
    debito, credito = (conta, banco) if movimento.sentido == "SAIDA" else (banco, conta)
    sugestao.conta_debito, sugestao.conta_credito = debito, credito
    sugestao.complemento = complemento_da_proposta(empresa, proposta, movimento)
    sugestao.confianca = confianca
    sugestao.origem = "IA"
    sugestao.justificativa = proposta.justificativa
    sugestao.padrao_id = None
    if confianca >= LIMIAR_APROVACAO:
        sugestao.status = "APROVADO"
        resultado.verdes += 1
    elif confianca >= 70:
        resultado.amarelas += 1
    else:
        resultado.vermelhas += 1
