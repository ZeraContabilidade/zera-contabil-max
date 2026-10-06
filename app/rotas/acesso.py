"""Entrar, sair, primeiro acesso e troca da própria senha."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.auth import (
    autenticar,
    existe_usuario,
    gerar_hash,
    iniciar_sessao,
    problema_na_senha,
    senha_confere,
    usuario_logado,
)
from app.db import obter_sessao
from app.modelos import Papel, Usuario
from app.servicos.usuarios import normalizar_email, normalizar_login, problemas_no_cadastro
from app.web import avisar, destino_seguro, pagina, redirecionar

router = APIRouter()


@router.get("/login")
def tela_login(request: Request, proximo: str = "/", sessao: Session = Depends(obter_sessao)):
    if not existe_usuario(sessao):
        return redirecionar("/primeiro-acesso")
    return pagina(request, "login.html", proximo=destino_seguro(proximo), login="")


@router.post("/login")
def entrar(
    request: Request,
    login: str = Form(""),
    senha: str = Form(""),
    proximo: str = Form("/"),
    sessao: Session = Depends(obter_sessao),
):
    usuario = autenticar(sessao, login, senha)
    if usuario is None:
        registrar_evento(sessao, "LOGIN_FALHOU", detalhe=f"Usuário digitado: {login.strip()[:100]}")
        sessao.commit()
        return pagina(
            request,
            "login.html",
            status_code=400,
            erro="Usuário ou senha incorretos. Confira e tente de novo.",
            login=login,
            proximo=destino_seguro(proximo),
        )
    sessao.info["usuario_id"] = usuario.id
    usuario.ultimo_acesso = datetime.now(UTC)
    registrar_evento(sessao, "LOGIN")
    sessao.commit()
    iniciar_sessao(request, usuario)
    return redirecionar(destino_seguro(proximo))


@router.post("/sair")
def sair(request: Request, sessao: Session = Depends(obter_sessao)):
    usuario_id = request.session.get("usuario_id")
    if usuario_id and sessao.get(Usuario, usuario_id):
        registrar_evento(sessao, "LOGOUT", usuario_id=usuario_id)
        sessao.commit()
    request.session.clear()
    return redirecionar("/login")


@router.get("/primeiro-acesso")
def tela_primeiro_acesso(request: Request, sessao: Session = Depends(obter_sessao)):
    if existe_usuario(sessao):
        return redirecionar("/login")
    return pagina(request, "primeiro_acesso.html", dados={}, erros=[])


@router.post("/primeiro-acesso")
def criar_primeiro_supervisor(
    request: Request,
    nome: str = Form(""),
    login: str = Form(""),
    email: str = Form(""),
    senha: str = Form(""),
    confirmacao: str = Form(""),
    sessao: Session = Depends(obter_sessao),
):
    if existe_usuario(sessao):
        return redirecionar("/login")
    erros = problemas_no_cadastro(sessao, nome, login, email)
    if problema := problema_na_senha(senha, confirmacao):
        erros.append(problema)
    if erros:
        dados = {"nome": nome, "login": login, "email": email}
        return pagina(request, "primeiro_acesso.html", status_code=400, dados=dados, erros=erros)

    usuario = Usuario(
        nome=nome.strip(),
        login=normalizar_login(login),
        email=normalizar_email(email),
        senha_hash=gerar_hash(senha),
        papel=Papel.SUPERVISOR,
    )
    sessao.add(usuario)
    sessao.commit()
    iniciar_sessao(request, usuario)
    avisar(request, "Cadastro do Supervisor concluído. Agora você já pode cadastrar os outros usuários.")
    return redirecionar("/")


@router.get("/minha-senha")
def tela_minha_senha(request: Request, usuario: Usuario = Depends(usuario_logado)):
    return pagina(request, "minha_senha.html", erro=None)


@router.post("/minha-senha")
def trocar_minha_senha(
    request: Request,
    senha_atual: str = Form(""),
    senha: str = Form(""),
    confirmacao: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if not senha_confere(usuario.senha_hash, senha_atual):
        erro = "A senha atual não confere. Digite de novo."
    else:
        erro = problema_na_senha(senha, confirmacao)
    if erro:
        return pagina(request, "minha_senha.html", status_code=400, erro=erro)
    usuario.senha_hash = gerar_hash(senha)
    sessao.commit()
    iniciar_sessao(request, usuario)  # continua logado aqui; outros logins abertos são encerrados
    avisar(request, "Senha alterada.")
    return redirecionar("/")
