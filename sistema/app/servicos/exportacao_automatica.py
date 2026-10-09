"""Exportação automática por empresa (§6.5): quando o mês está todo aprovado e o saldo de todos os extratos confere,
o lanctos.txt sai sozinho e o Painel avisa (“Casa Criança — agosto/2026 pronto para importar”).

Desligada por padrão: o Supervisor liga no cadastro da empresa quando confiar. É conservadora — só gera quando não
há nada pendente nem com problema, todo extrato do mês confere o saldo e vai até o último dia do mês, não falta o
extrato de nenhuma conta que teve extrato no mês anterior e o mês não foi reaberto pelo Supervisor (mês reaberto é
sempre exportado à mão). `motivo_para_esperar` diz por que ainda não gerou (aparece no Painel e na aba Exportar).
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import Empresa, Exportacao, MovimentoExtrato, Sugestao
from app.servicos.exportacao import exportar, preparar
from app.servicos.extratos import extratos_do_mes, limites_do_mes


def meses_entre(inicio: date, fim: date) -> list[date]:
    """Os meses (1º dia) que um período toca: 25/07 a 10/08 → [julho, agosto]."""
    meses, mes = [], inicio.replace(day=1)
    while mes <= fim:
        meses.append(mes)
        mes = date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)
    return meses


def _mes_anterior(competencia: date) -> date:
    return date(competencia.year - (competencia.month == 1), (competencia.month - 2) % 12 + 1, 1)


def motivo_para_esperar(sessao: Session, empresa: Empresa, competencia: date) -> str | None:
    """None = pode gerar sozinho agora. Senão, em português, o que falta."""
    if not empresa.exportacao_automatica:
        return "exportação automática desligada"
    reaberta = sessao.scalar(
        select(Exportacao.id).where(
            Exportacao.empresa_id == empresa.id,
            Exportacao.competencia <= competencia,  # o mês ou um período que o inclui
            func.coalesce(Exportacao.competencia_fim, Exportacao.competencia) >= competencia,
            Exportacao.reaberta_em.is_not(None),
        )
    )
    if reaberta:
        return "mês reaberto pelo Supervisor: gere o arquivo à mão"
    preparo = preparar(sessao, empresa, competencia)
    if preparo.pendentes:
        return f"{len(preparo.pendentes)} linha(s) pendente(s) na Revisão"
    if preparo.problemas:
        return f"{len(preparo.problemas)} problema(s) na aba Exportar"
    if not preparo.prontas:
        return "nada novo para exportar"
    _, ultimo_dia = limites_do_mes(competencia)
    extratos = extratos_do_mes(sessao, empresa, competencia)
    for conta in preparo.disponiveis:
        da_conta = [e for e in extratos if e.conta_bancaria_id == conta.id]
        if any(e.conferencia != "CONFERE" for e in da_conta):
            return f"o saldo do extrato de {conta.rotulo} não conferiu"
        ate = max((e.fim for e in da_conta), default=None)
        if ate is None:
            return f"falta o extrato de {conta.rotulo}"
        if ate < ultimo_dia:
            return f"o extrato de {conta.rotulo} vai só até {ate:%d/%m}"
    anteriores = {e.conta_bancaria for e in extratos_do_mes(sessao, empresa, _mes_anterior(competencia))}
    deste_mes = {e.conta_bancaria_id for e in extratos}
    if faltando := sorted(c.rotulo for c in anteriores if c.id not in deste_mes):
        return f"falta o extrato de {faltando[0]} (teve extrato no mês anterior)"
    return None


def exportar_se_pronto(sessao: Session, empresa: Empresa, competencia: date) -> Exportacao | None:
    """Gera o lanctos.txt do mês sozinho, se tudo estiver pronto (ninguém é o autor: fica marcada como automática)."""
    if motivo_para_esperar(sessao, empresa, competencia) is not None:
        return None
    return exportar(sessao, empresa, competencia, None, None, automatica=True)


def meses_das_sugestoes(sessao: Session, ids: list[int]) -> list[date]:
    datas = sessao.scalars(
        select(MovimentoExtrato.data)
        .join(Sugestao, Sugestao.movimento_id == MovimentoExtrato.id)
        .where(Sugestao.id.in_(ids))
        .distinct()
    )
    return sorted({d.replace(day=1) for d in datas})


def prontos_para_importar(sessao: Session) -> list[Exportacao]:
    """Gerados sozinhos e ainda não baixados por ninguém (o aviso do Painel)."""
    return list(
        sessao.scalars(
            select(Exportacao)
            .where(Exportacao.automatica, Exportacao.baixado_em.is_(None), Exportacao.reaberta_em.is_(None))
            .order_by(Exportacao.criado_em)
        )
    )
