"""Contas-chave da empresa (na aba Plano de Contas): refazer a auto-configuração, trocar a conta e
ligar uma conta bancária."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.modelos import ContaChave, Empresa, Usuario
from app.rotas.comum import buscar_empresa
from app.servicos.contas_chave import (
    TIPOS_BANCARIOS,
    auto_configurar,
    escolher_conta,
    ligar_conta_bancaria,
    nome_do_tipo,
)
from app.web import avisar, redirecionar

router = APIRouter()


def _destino(empresa: Empresa) -> str:
    return f"/empresas/{empresa.id}?aba=plano#contas-chave"


def avisar_auto_configuracao(request: Request, resultado) -> None:
    """Usado também depois de importar o plano."""
    if not resultado.chaves:
        return
    avisar(request, resultado.resumo(), "ok" if not resultado.nao_encontradas else "atencao")
    if resultado.aviso_ia:
        avisar(request, f"Sem a ajuda da IA nesta configuração: {resultado.aviso_ia}", "atencao")


@router.post("/empresas/{empresa_id}/contas-chave/refazer")
def refazer(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    resultado = auto_configurar(sessao, empresa, usuario)
    sessao.commit()
    if not resultado.chaves:
        avisar(request, "Importe o plano de contas primeiro.", "atencao")
    avisar_auto_configuracao(request, resultado)
    return redirecionar(_destino(empresa))


@router.post("/empresas/{empresa_id}/contas-chave/banco")
def ligar_banco(
    request: Request,
    empresa_id: int,
    banco: str = Form(""),
    agencia: str = Form(""),
    numero: str = Form(""),
    tipo: str = Form("BANCO"),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if not banco.strip() or not numero.strip() or tipo not in TIPOS_BANCARIOS:
        avisar(
            request, "Informe o banco, o número da conta e o tipo (corrente, poupança ou aplicação).", "erro"
        )
        return redirecionar(_destino(empresa))
    chave, aviso_ia = ligar_conta_bancaria(sessao, empresa, banco, agencia, numero, tipo, usuario)
    sessao.commit()
    if chave.conta_id:
        avisar(request, f"🤖 {nome_do_tipo(tipo)} {chave.referencia} → {chave.conta.rotulo}.")
    else:
        avisar(request, chave.justificativa or "Conta não encontrada no plano.", "atencao")
    if aviso_ia:
        avisar(request, f"Sem a ajuda da IA: {aviso_ia}", "atencao")
    return redirecionar(_destino(empresa))


@router.post("/empresas/{empresa_id}/contas-chave/{chave_id}")
def trocar_conta(
    request: Request,
    empresa_id: int,
    chave_id: int,
    conta: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    chave = sessao.get(ContaChave, chave_id)
    if chave is None or chave.empresa_id != empresa.id:
        avisar(request, "Conta-chave não encontrada.", "erro")
        return redirecionar(_destino(empresa))
    if erro := escolher_conta(sessao, chave, conta, usuario):
        avisar(request, erro, "erro")
        return redirecionar(_destino(empresa))
    sessao.commit()
    avisar(request, f"{nome_do_tipo(chave.tipo)}: agora usa {chave.conta.rotulo}.")
    return redirecionar(_destino(empresa))
