"""Painel do Supervisor: todas as empresas no mês (ou período) escolhido (§2)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import exigir_supervisor
from app.db import obter_sessao
from app.modelos import Empresa, Usuario
from app.servicos.painel import painel
from app.web import competencia_da_tela, pagina

router = APIRouter()


@router.get("/painel")
def tela_painel(
    request: Request,
    mes: str | None = None,
    ate: str | None = None,
    responsavel: str = "",
    pendencia: str = "",
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    competencia = competencia_da_tela(request, mes, ate)
    responsavel_id = int(responsavel) if responsavel.isdigit() else None
    usuarios = list(sessao.scalars(select(Usuario).where(Usuario.ativo).order_by(Usuario.nome)))
    dados = painel(sessao, competencia, responsavel_id, bool(pendencia))
    ids = {e.empresa_id for e in dados.prontos}
    nomes_empresas = {e.id: e.nome for e in sessao.scalars(select(Empresa).where(Empresa.id.in_(ids)))} if ids else {}
    return pagina(
        request,
        "painel.html",
        dados=dados,
        nomes_empresas=nomes_empresas,
        competencia=competencia,
        usuarios=usuarios,
        responsavel_id=responsavel_id,
        pendencia=bool(pendencia),
    )
