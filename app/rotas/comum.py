"""Ajudantes usados por várias telas."""

from fastapi import Request
from sqlalchemy.orm import Session

from app.modelos import Empresa
from app.servicos.empresas import ResultadoConsulta, descrever_campos
from app.web import avisar


def buscar_empresa(sessao: Session, request: Request, empresa_id: int) -> Empresa | None:
    """A empresa pedida, ou None com o aviso “Empresa não encontrada.” (a tela volta para a lista)."""
    empresa = sessao.get(Empresa, empresa_id)
    if empresa is None:
        avisar(request, "Empresa não encontrada.", "erro")
    return empresa


def avisar_consulta(request: Request, resultado: ResultadoConsulta) -> None:
    if resultado.situacao == "falhou":
        avisar(
            request,
            "Não consegui consultar o CNPJ na internet agora. Pode preencher à mão "
            "ou clicar em “Buscar dados públicos do CNPJ” mais tarde.",
            "atencao",
        )
    elif resultado.preenchidos:
        avisar(
            request,
            f"🤖 Preenchido pela consulta pública do CNPJ: {descrever_campos(resultado.preenchidos)}.",
        )
