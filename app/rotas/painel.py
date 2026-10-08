"""Painel do Supervisor: todas as empresas no mês escolhido (§2)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import exigir_supervisor
from app.db import obter_sessao
from app.modelos import Usuario
from app.servicos.painel import painel
from app.web import competencia_da_tela, pagina

router = APIRouter()


@router.get("/painel")
def tela_painel(
    request: Request,
    mes: str | None = None,
    responsavel: str = "",
    pendencia: str = "",
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    competencia = competencia_da_tela(request, mes)
    responsavel_id = int(responsavel) if responsavel.isdigit() else None
    usuarios = list(sessao.scalars(select(Usuario).where(Usuario.ativo).order_by(Usuario.nome)))
    return pagina(
        request,
        "painel.html",
        dados=painel(sessao, competencia, responsavel_id, bool(pendencia)),
        competencia=competencia,
        usuarios=usuarios,
        responsavel_id=responsavel_id,
        pendencia=bool(pendencia),
    )
