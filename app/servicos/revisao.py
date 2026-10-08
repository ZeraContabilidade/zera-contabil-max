"""Revisão das sugestões (§3.5, §6.3): o usuário confere, corrige, aprova ou ignora — e cada decisão ensina.

Aprovar ou corrigir uma linha grava um lançamento no histórico da empresa (importação “Revisão”, uma por
empresa) e recalcula os padrões: na próxima vez a mesma linha sai pelas regras, sem IA. A linha conferida
(`conferido_por_id`) nunca mais é mexida pela classificação automática nem pela IA.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modelos import (
    ContaContabil,
    Empresa,
    Importacao,
    LancamentoHistorico,
    MovimentoExtrato,
    Padrao,
    Sugestao,
    Usuario,
)
from app.servicos.aprendizado import CNPJ_NO_TEXTO, aprender, normalizar_nome, separar_complemento
from app.servicos.contas_chave import achar_conta_analitica
from app.servicos.documentos import normalizar_documento, tipo_documento
from app.servicos.extratos import limites_do_mes

FILTROS = {
    "atencao": "Precisa de atenção",
    "pendentes": "Pendentes",
    "amarelas": "Para conferir",
    "ia": "Só IA",
    "aprovados": "Aprovados",
    "todos": "Todos",
}
APRENDE_COM = ("NOME", "CNPJ", "PALAVRA", "VALOR", "IA", "USUARIO", "PENDENTE")  # regra e transferência não


def banco_do_movimento(movimento: MovimentoExtrato) -> ContaContabil | None:
    chave = movimento.conta_bancaria.conta_chave
    return chave.conta if chave and chave.conta_id else None


def contrapartida(sugestao: Sugestao) -> ContaContabil | None:
    """O lado que não é o banco do movimento: débito numa saída, crédito numa entrada."""
    return sugestao.conta_debito if sugestao.movimento.sentido == "SAIDA" else sugestao.conta_credito


def sugestoes_do_mes(
    sessao: Session,
    empresa: Empresa,
    competencia: date,
    filtro: str = "atencao",
    busca: str = "",
    conta: int | None = None,
) -> list[Sugestao]:
    inicio, fim = limites_do_mes(competencia)
    consulta = (
        select(Sugestao)
        .join(MovimentoExtrato, Sugestao.movimento_id == MovimentoExtrato.id)
        .where(Sugestao.empresa_id == empresa.id, MovimentoExtrato.data.between(inicio, fim))
    )
    if filtro == "atencao":
        consulta = consulta.where(Sugestao.status == "PENDENTE")
    elif filtro == "pendentes":
        consulta = consulta.where(Sugestao.status == "PENDENTE", Sugestao.confianca < 70)
    elif filtro == "amarelas":
        consulta = consulta.where(Sugestao.status == "PENDENTE", Sugestao.confianca >= 70)
    elif filtro == "ia":
        consulta = consulta.where(Sugestao.origem == "IA")
    elif filtro == "aprovados":
        consulta = consulta.where(Sugestao.status.in_(("APROVADO", "EXPORTADO")))
    if busca := busca.strip():
        padrao = f"%{busca}%"
        consulta = consulta.where(
            or_(
                func.unaccent(MovimentoExtrato.historico).ilike(func.unaccent(padrao)),
                func.unaccent(MovimentoExtrato.complemento).ilike(func.unaccent(padrao)),
                func.unaccent(Sugestao.complemento).ilike(func.unaccent(padrao)),
            )
        )
    if conta:
        ids = select(ContaContabil.id).where(ContaContabil.empresa_id == empresa.id, ContaContabil.reduzido == conta)
        consulta = consulta.where(or_(Sugestao.conta_debito_id.in_(ids), Sugestao.conta_credito_id.in_(ids)))
    ordem = (MovimentoExtrato.data, MovimentoExtrato.conta_bancaria_id, MovimentoExtrato.ordem)
    return list(sessao.scalars(consulta.order_by(*ordem)))


@dataclass
class Contagem:
    verde: int = 0
    amarela: int = 0
    vermelha: int = 0
    cinza: int = 0

    @property
    def total(self) -> int:
        return self.verde + self.amarela + self.vermelha + self.cinza


def contagem_do_mes(sessao: Session, empresa: Empresa, competencia: date) -> Contagem:
    contagem = Contagem()
    for sugestao in sugestoes_do_mes(sessao, empresa, competencia, "todos"):
        setattr(contagem, sugestao.cor, getattr(contagem, sugestao.cor) + 1)
    return contagem


# ---------------------------------------------------------------- decisões


def achar_conta_digitada(sessao: Session, empresa_id: int, texto: str) -> tuple[ContaContabil | None, str | None]:
    """“355”, “355 – ÁGUA E ESGOTO” ou só parte do nome (“agua”) — o nome vale quando uma conta só combina."""
    if re.match(r"\s*\d", texto or ""):
        return achar_conta_analitica(sessao, empresa_id, texto)
    nome = " ".join((texto or "").split())
    if len(nome) < 3:
        return None, "Digite o código reduzido ou parte do nome da conta (ex.: 355 ou “agua”)."
    contas = sessao.scalars(
        select(ContaContabil)
        .where(
            ContaContabil.empresa_id == empresa_id,
            ContaContabil.ativa,
            ContaContabil.tipo == "A",
            func.unaccent(ContaContabil.descricao).ilike(func.unaccent(f"%{nome}%")),
        )
        .order_by(ContaContabil.reduzido)
        .limit(6)
    ).all()
    if len(contas) == 1:
        return contas[0], None
    if not contas:
        return None, f"Nenhuma conta analítica tem “{nome}” no nome. Digite o código ou escolha na lista."
    exemplos = ", ".join(c.rotulo for c in contas[:5]) + ("…" if len(contas) > 5 else "")
    return None, f"Mais de uma conta tem “{nome}” no nome: {exemplos}. Digite o código da conta certa."


def _conferir(sugestao: Sugestao, usuario: Usuario | None, status: str) -> None:
    sugestao.status = status
    sugestao.conferido_por_id = usuario.id if usuario else None
    sugestao.conferido_em = datetime.now(UTC)


def aprovar(sessao: Session, sugestao: Sugestao, usuario: Usuario | None) -> str | None:
    """Aprova como está. Devolve um erro em português quando a linha não pode ser aprovada."""
    if contrapartida(sugestao) is None and sugestao.origem != "TRANSFERENCIA":
        return "Escolha a conta antes de aprovar."
    _conferir(sugestao, usuario, "APROVADO")
    _aprender_com(sessao, sugestao)
    return None


def corrigir(
    sessao: Session, sugestao: Sugestao, conta: ContaContabil, complemento: str, usuario: Usuario | None
) -> None:
    """O usuário escolheu a conta (e o complemento): vale e ensina."""
    movimento = sugestao.movimento
    banco = banco_do_movimento(movimento)
    if movimento.sentido == "SAIDA":
        sugestao.conta_debito, sugestao.conta_credito = conta, banco
    else:
        sugestao.conta_debito, sugestao.conta_credito = banco, conta
    if complemento := " ".join(complemento.replace(";", ",").split())[:300]:
        sugestao.complemento = complemento
    sugestao.origem = "USUARIO"
    sugestao.confianca = 100
    sugestao.justificativa = "Escolhido na Revisão."
    _conferir(sugestao, usuario, "APROVADO")
    _aprender_com(sessao, sugestao)


def ignorar(sessao: Session, sugestao: Sugestao, usuario: Usuario | None) -> None:
    """Sem lançamento (ex.: estorno que se anula, movimento que não é da empresa)."""
    _conferir(sugestao, usuario, "IGNORADO")
    _aprender_com(sessao, sugestao)


def reabrir(sessao: Session, sugestao: Sugestao) -> None:
    """Desfaz a conferência: a linha volta a pendente e a classificação automática pode mexer de novo."""
    sugestao.status = "PENDENTE"
    sugestao.conferido_por_id = None
    sugestao.conferido_em = None
    _aprender_com(sessao, sugestao)


def parecidas(sessao: Session, sugestao: Sugestao) -> list[Sugestao]:
    """Outras linhas do mesmo mês, ainda não conferidas, com o mesmo favorecido do banco (ou o mesmo CNPJ)."""
    movimento = sugestao.movimento
    nome = normalizar_nome(movimento.complemento or movimento.historico)
    documentos = {normalizar_documento(m.group(0)) for m in CNPJ_NO_TEXTO.finditer(movimento.complemento or "")}
    inicio, fim = limites_do_mes(movimento.data.replace(day=1))
    candidatas = sessao.scalars(
        select(Sugestao)
        .join(MovimentoExtrato, Sugestao.movimento_id == MovimentoExtrato.id)
        .where(
            Sugestao.empresa_id == sugestao.empresa_id,
            Sugestao.id != sugestao.id,
            Sugestao.conferido_por_id.is_(None),
            Sugestao.status != "EXPORTADO",
            MovimentoExtrato.sentido == movimento.sentido,
            MovimentoExtrato.data.between(inicio, fim),
        )
    )
    escolhida = contrapartida(sugestao)
    resultado = []
    for outra in candidatas:
        texto = outra.movimento.complemento or outra.movimento.historico
        mesmo_nome = bool(nome) and normalizar_nome(texto) == nome
        mesmo_documento = bool(documentos) and any(d in normalizar_documento(texto) for d in documentos)
        if (mesmo_nome or mesmo_documento) and contrapartida(outra) != escolhida:
            resultado.append(outra)
    return resultado


# ---------------------------------------------------------------- aprendizado contínuo (§6.3)


def _importacao_da_revisao(sessao: Session, empresa_id: int) -> Importacao:
    importacao = sessao.scalar(
        select(Importacao).where(Importacao.empresa_id == empresa_id, Importacao.tipo == "REVISAO")
    )
    if importacao is None:
        importacao = Importacao(empresa_id=empresa_id, tipo="REVISAO", resumo={"formato": "Revisão dos extratos"})
        sessao.add(importacao)
        sessao.flush()
    return importacao


def _aprender_com(sessao: Session, sugestao: Sugestao) -> None:
    """A decisão do usuário vira (ou deixa de ser) um lançamento do histórico; os padrões são recalculados."""
    marca = hashlib.sha256(f"revisao|{sugestao.id}".encode()).hexdigest()
    lancamento = sessao.scalar(
        select(LancamentoHistorico).where(
            LancamentoHistorico.empresa_id == sugestao.empresa_id, LancamentoHistorico.marca == marca
        )
    )
    movimento = sugestao.movimento
    outra = contrapartida(sugestao)
    ensina = (
        sugestao.status == "APROVADO"
        and sugestao.conferido_por_id is not None
        and sugestao.origem in APRENDE_COM
        and outra is not None
    )
    if not ensina:
        if lancamento is not None:
            sessao.delete(lancamento)
            _reaprender(sessao, sugestao)
        return
    partes = separar_complemento(sugestao.complemento)
    padrao = sessao.get(Padrao, sugestao.padrao_id) if sugestao.padrao_id else None
    # favorecido: o nome do padrão quando foi ele que achou (reforça o mesmo); senão como o BANCO escreve,
    # para a mesma linha do extrato sair pelo nome no mês que vem
    favorecido = padrao.nome if padrao and padrao.tipo != "PALAVRA" else (movimento.complemento or movimento.historico)
    documento = next(
        (d for m in CNPJ_NO_TEXTO.finditer(f"{movimento.complemento or ''} {sugestao.complemento}")
         if tipo_documento(d := normalizar_documento(m.group(0)))),
        None,
    )  # fmt: skip
    campos = {  # tudo calculado antes de criar a linha (uma consulta no meio gravaria a linha pela metade)
        "data": movimento.data,
        "valor": movimento.valor,
        "conta_debito_id": sugestao.conta_debito.id if sugestao.conta_debito else None,
        "conta_credito_id": sugestao.conta_credito.id if sugestao.conta_credito else None,
        "historico": sugestao.complemento or movimento.descricao,
        "favorecido": favorecido[:200],
        "cnpj_cpf": (padrao.cnpj_cpf if padrao else None) or documento,
        "natureza": partes.natureza[:200] or None,
        "sentido": movimento.sentido,
        "contrapartida_id": outra.id,
    }
    if lancamento is None:
        importacao_id = _importacao_da_revisao(sessao, sugestao.empresa_id).id
        sessao.add(
            LancamentoHistorico(
                empresa_id=sugestao.empresa_id, importacao_id=importacao_id, marca=marca, revisado_ia=True, **campos
            )
        )
    else:
        for campo, valor in campos.items():
            setattr(lancamento, campo, valor)
    _reaprender(sessao, sugestao)


def _reaprender(sessao: Session, sugestao: Sugestao) -> None:
    sessao.flush()
    aprender(sessao, sessao.get(Empresa, sugestao.empresa_id), registrar=False)
