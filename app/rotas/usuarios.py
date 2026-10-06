"""Cadastro de usuários e consulta do log (só Supervisor)."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import exigir_supervisor, gerar_hash, iniciar_sessao, problema_na_senha
from app.db import obter_sessao
from app.modelos import Log, Papel, Usuario
from app.servicos.usuarios import (
    deixaria_sem_supervisor,
    ler_papel,
    normalizar_email,
    normalizar_login,
    problemas_no_cadastro,
)
from app.web import avisar, pagina, redirecionar

router = APIRouter()
LIMITE_LOG = 200


def _tela_lista(request: Request, sessao: Session, status_code: int = 200, dados=None, erros=None):
    usuarios = sessao.scalars(select(Usuario).order_by(Usuario.ativo.desc(), Usuario.nome)).all()
    return pagina(
        request,
        "usuarios.html",
        status_code=status_code,
        usuarios=usuarios,
        papeis=list(Papel),
        dados=dados or {"papel": Papel.ASSISTENTE.value},
        erros=erros or [],
    )


@router.get("/usuarios")
def lista_usuarios(
    request: Request,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    return _tela_lista(request, sessao)


@router.post("/usuarios")
def criar_usuario(
    request: Request,
    nome: str = Form(""),
    login: str = Form(""),
    email: str = Form(""),
    papel: str = Form(""),
    senha: str = Form(""),
    confirmacao: str = Form(""),
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    erros = problemas_no_cadastro(sessao, nome, login, email)
    papel_ok = ler_papel(papel)
    if papel_ok is None:
        erros.append("Escolha o papel do usuário.")
    if problema := problema_na_senha(senha, confirmacao):
        erros.append(problema)
    if erros:
        dados = {"nome": nome, "login": login, "email": email, "papel": papel}
        return _tela_lista(request, sessao, status_code=400, dados=dados, erros=erros)

    novo = Usuario(
        nome=nome.strip(),
        login=normalizar_login(login),
        email=normalizar_email(email),
        senha_hash=gerar_hash(senha),
        papel=papel_ok,
    )
    sessao.add(novo)
    sessao.commit()
    avisar(
        request, f"Usuário {novo.nome} cadastrado. Passe para a pessoa o usuário “{novo.login}” e a senha."
    )
    return redirecionar("/usuarios")


def _buscar(sessao: Session, request: Request, usuario_id: int) -> Usuario | None:
    usuario = sessao.get(Usuario, usuario_id)
    if usuario is None:
        avisar(request, "Usuário não encontrado.", "erro")
    return usuario


@router.get("/usuarios/{usuario_id}")
def tela_editar_usuario(
    request: Request,
    usuario_id: int,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    if (alvo := _buscar(sessao, request, usuario_id)) is None:
        return redirecionar("/usuarios")
    return pagina(request, "usuario_editar.html", alvo=alvo, papeis=list(Papel), erros=[], erro_senha=None)


@router.post("/usuarios/{usuario_id}")
def editar_usuario(
    request: Request,
    usuario_id: int,
    nome: str = Form(""),
    email: str = Form(""),
    papel: str = Form(""),
    ativo: str | None = Form(None),
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    if (alvo := _buscar(sessao, request, usuario_id)) is None:
        return redirecionar("/usuarios")
    erros = problemas_no_cadastro(sessao, nome, alvo.login, email, ignorar_id=alvo.id)
    papel_ok = ler_papel(papel)
    novo_ativo = ativo is not None
    if papel_ok is None:
        erros.append("Escolha o papel do usuário.")
    elif deixaria_sem_supervisor(sessao, alvo, papel_ok, novo_ativo):
        erros.append(
            "O sistema precisa de pelo menos um Supervisor ativo. "
            "Cadastre (ou promova) outro Supervisor antes de alterar este."
        )
    if erros:
        return pagina(
            request,
            "usuario_editar.html",
            status_code=400,
            alvo=alvo,
            papeis=list(Papel),
            erros=erros,
            erro_senha=None,
        )
    alvo.nome = nome.strip()
    alvo.email = normalizar_email(email)
    alvo.papel = papel_ok
    alvo.ativo = novo_ativo
    sessao.commit()
    avisar(request, f"Cadastro de {alvo.nome} atualizado.")
    return redirecionar("/usuarios")


@router.post("/usuarios/{usuario_id}/senha")
def redefinir_senha(
    request: Request,
    usuario_id: int,
    senha: str = Form(""),
    confirmacao: str = Form(""),
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    if (alvo := _buscar(sessao, request, usuario_id)) is None:
        return redirecionar("/usuarios")
    if erro := problema_na_senha(senha, confirmacao):
        return pagina(
            request,
            "usuario_editar.html",
            status_code=400,
            alvo=alvo,
            papeis=list(Papel),
            erros=[],
            erro_senha=erro,
        )
    alvo.senha_hash = gerar_hash(senha)
    sessao.commit()
    if alvo.id == supervisor.id:
        iniciar_sessao(request, alvo)
    avisar(request, f"Senha de {alvo.nome} redefinida. Passe a senha nova para a pessoa.")
    return redirecionar("/usuarios")


@router.get("/log")
def tela_log(
    request: Request,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    registros = sessao.scalars(
        select(Log).options(joinedload(Log.usuario)).order_by(Log.id.desc()).limit(LIMITE_LOG)
    ).all()
    return pagina(request, "log.html", registros=registros, limite=LIMITE_LOG)
