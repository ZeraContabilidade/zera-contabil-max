"""Senhas, login e permissões."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import obter_sessao
from app.modelos import Papel, Usuario

TAMANHO_MINIMO_SENHA = 8
_hasher = PasswordHasher()


class NaoAutenticado(Exception):
    """Ninguém logado (ou o login expirou): vai para a tela de entrada."""


class SemPermissao(Exception):
    """Usuário logado, mas o papel dele não permite a ação."""


def gerar_hash(senha: str) -> str:
    return _hasher.hash(senha)


def senha_confere(senha_hash: str, senha: str) -> bool:
    try:
        return _hasher.verify(senha_hash, senha)
    except (VerificationError, InvalidHashError):
        return False


def problema_na_senha(senha: str, confirmacao: str) -> str | None:
    if len(senha) < TAMANHO_MINIMO_SENHA:
        return f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres."
    if senha != confirmacao:
        return "As duas senhas digitadas não são iguais. Digite de novo."
    return None


def chave_da_sessao(usuario: Usuario) -> str:
    """Muda quando a senha muda: trocar a senha encerra os logins abertos em outros lugares."""
    return usuario.senha_hash[-16:]


def existe_usuario(sessao: Session) -> bool:
    return sessao.scalar(select(func.count()).select_from(Usuario)) > 0


def autenticar(sessao: Session, login: str, senha: str) -> Usuario | None:
    texto = login.strip().lower()
    usuario = sessao.scalar(select(Usuario).where(or_(Usuario.login == texto, Usuario.email == texto)))
    if usuario is None or not usuario.ativo or not senha_confere(usuario.senha_hash, senha):
        return None
    if _hasher.check_needs_rehash(usuario.senha_hash):
        usuario.senha_hash = gerar_hash(senha)
    return usuario


def iniciar_sessao(request: Request, usuario: Usuario) -> None:
    request.session.clear()
    request.session.update(usuario_id=usuario.id, chave=chave_da_sessao(usuario))


def usuario_logado(request: Request, sessao: Session = Depends(obter_sessao)) -> Usuario:
    usuario_id = request.session.get("usuario_id")
    usuario = sessao.get(Usuario, usuario_id) if usuario_id else None
    if usuario is None or not usuario.ativo or request.session.get("chave") != chave_da_sessao(usuario):
        request.session.clear()
        raise NaoAutenticado()
    sessao.info["usuario_id"] = usuario.id  # a auditoria registra quem fez cada alteração
    request.state.usuario = usuario
    return usuario


def exigir_supervisor(usuario: Usuario = Depends(usuario_logado)) -> Usuario:
    if usuario.papel != Papel.SUPERVISOR:
        raise SemPermissao("Só o Supervisor pode acessar esta tela.")
    return usuario
