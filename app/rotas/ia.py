"""Painel de uso da IA (só Supervisor): situação, gasto do mês, por empresa e últimas chamadas."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import exigir_supervisor
from app.db import obter_sessao
from app.ia.cliente import ErroIA
from app.ia.servico import custo_estimado, dolar, inicio_do_mes, situacao_ia, testar_conexao
from app.modelos import ChamadaIA, Empresa, Usuario
from app.servicos.painel import uso_da_ia_por_empresa
from app.web import avisar, pagina, redirecionar

router = APIRouter()


@router.get("/ia")
def painel_ia(
    request: Request,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    por_empresa = sessao.execute(
        select(
            Empresa,
            func.count(ChamadaIA.id),
            func.count(ChamadaIA.id).filter(ChamadaIA.sucesso),
            func.coalesce(func.sum(ChamadaIA.custo_usd), 0),
        )
        .join(ChamadaIA, ChamadaIA.empresa_id == Empresa.id)
        .where(ChamadaIA.quando >= inicio_do_mes())
        .group_by(Empresa.id)
        .order_by(func.sum(ChamadaIA.custo_usd).desc())
    ).all()
    sem_empresa = sessao.execute(
        select(func.count(ChamadaIA.id), func.coalesce(func.sum(ChamadaIA.custo_usd), 0)).where(
            ChamadaIA.quando >= inicio_do_mes(), ChamadaIA.empresa_id.is_(None)
        )
    ).one()
    ultimas = sessao.scalars(
        select(ChamadaIA).options(joinedload(ChamadaIA.empresa)).order_by(ChamadaIA.id.desc()).limit(50)
    ).all()
    return pagina(
        request,
        "ia.html",
        situacao=situacao_ia(sessao),
        por_empresa=por_empresa,
        sem_empresa=sem_empresa,
        ultimas=ultimas,
        uso=uso_da_ia_por_empresa(sessao),
    )


@router.post("/ia/testar")
def testar_ia(
    request: Request,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    try:
        resposta = testar_conexao(sessao, supervisor)
    except ErroIA as erro:
        avisar(request, str(erro), "erro")
        return redirecionar("/ia")
    custo = custo_estimado(resposta.modelo, resposta.uso)
    avisar(
        request,
        f"✔ A IA respondeu: “{resposta.dados.get('mensagem', '')}” "
        f"(modelo {resposta.modelo}, custo estimado {dolar(custo, 4)}).",
    )
    return redirecionar("/ia")
