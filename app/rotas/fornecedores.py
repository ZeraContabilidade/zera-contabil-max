"""Lista “Fornecedores a cadastrar no Domínio” (aba Revisão): dar baixa à mão, descartar e baixar em Excel."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.modelos import FornecedorACadastrar, Usuario
from app.rotas.comum import buscar_empresa
from app.servicos.fornecedores import descartar, ja_cadastrei, planilha
from app.servicos.revisao import achar_conta_digitada
from app.web import avisar, redirecionar

router = APIRouter()
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/empresas/{empresa_id}/fornecedores/{fornecedor_id}")
def resolver_fornecedor(
    request: Request,
    empresa_id: int,
    fornecedor_id: int,
    acao: str = Form(""),
    conta: str = Form(""),
    mes: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    voltar = f"/empresas/{empresa.id}?" + urlencode({"aba": "revisao", "mes": mes})
    fornecedor = sessao.get(FornecedorACadastrar, fornecedor_id)
    if fornecedor is None or fornecedor.empresa_id != empresa.id or fornecedor.situacao != "A_CADASTRAR":
        avisar(request, "Este fornecedor não está mais na lista (já foi resolvido).", "erro")
        return redirecionar(voltar)
    if acao == "cadastrado":
        escolhida, erro = achar_conta_digitada(sessao, empresa.id, conta)
        if erro:
            avisar(request, f"{fornecedor.nome}: {erro}", "erro")
            return redirecionar(voltar)
        linhas = ja_cadastrei(sessao, empresa, fornecedor, escolhida, usuario)
        sessao.commit()
        avisar(
            request, f"{fornecedor.nome}: conta {escolhida.rotulo} gravada em {linhas} linha(s), que ficaram aprovadas."
        )
    elif acao == "descartar":
        linhas = descartar(sessao, fornecedor)
        sessao.commit()
        avisar(request, f"{fornecedor.nome} saiu da lista. {linhas} linha(s) voltaram a pendentes: escolha a conta.")
    else:
        avisar(request, "Escolha “Já cadastrei” (com o código da conta) ou “Não é fornecedor”.", "erro")
    return redirecionar(voltar)


@router.get("/empresas/{empresa_id}/fornecedores-a-cadastrar.xlsx")
def baixar_fornecedores(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    nome = f"fornecedores_a_cadastrar_{empresa.codigo_dominio}.xlsx"
    return Response(
        planilha(sessao, empresa),
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
