"""Ajudantes usados por várias telas."""

from fastapi import Request
from sqlalchemy.orm import Session

from app.modelos import Empresa
from app.web import avisar


def buscar_empresa(sessao: Session, request: Request, empresa_id: int) -> Empresa | None:
    """A empresa pedida, ou None com o aviso “Empresa não encontrada.” (a tela volta para a lista)."""
    empresa = sessao.get(Empresa, empresa_id)
    if empresa is None:
        avisar(request, "Empresa não encontrada.", "erro")
    return empresa
