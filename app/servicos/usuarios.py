"""Regras do cadastro de usuários."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import Papel, Usuario

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalizar_login(login: str) -> str:
    return login.strip().lower()


def normalizar_email(email: str) -> str | None:
    return email.strip().lower() or None


def problemas_no_cadastro(
    sessao: Session, nome: str, login: str, email: str, ignorar_id: int | None = None
) -> list[str]:
    erros = []
    if not nome.strip():
        erros.append("Preencha o nome.")
    login_ok = normalizar_login(login)
    if len(login_ok) < 3 or " " in login_ok:
        erros.append(
            "O usuário para entrar precisa ter pelo menos 3 letras e nenhum espaço (ex.: maria.silva)."
        )
    elif _em_uso(sessao, Usuario.login, login_ok, ignorar_id):
        erros.append(f"O usuário “{login_ok}” já está em uso. Escolha outro.")
    email_ok = normalizar_email(email)
    if email_ok and not _EMAIL.match(email_ok):
        erros.append("O e-mail parece incompleto. Confira (ex.: maria@zera.com.br) ou deixe em branco.")
    elif email_ok and _em_uso(sessao, Usuario.email, email_ok, ignorar_id):
        erros.append(f"O e-mail “{email_ok}” já pertence a outro usuário.")
    return erros


def _em_uso(sessao: Session, coluna, valor: str, ignorar_id: int | None) -> bool:
    consulta = select(func.count()).select_from(Usuario).where(coluna == valor)
    if ignorar_id is not None:
        consulta = consulta.where(Usuario.id != ignorar_id)
    return sessao.scalar(consulta) > 0


def ler_papel(texto: str) -> Papel | None:
    try:
        return Papel(texto)
    except ValueError:
        return None


def deixaria_sem_supervisor(sessao: Session, usuario: Usuario, novo_papel: Papel, novo_ativo: bool) -> bool:
    """O sistema precisa sempre de pelo menos um Supervisor ativo."""
    if not (usuario.papel == Papel.SUPERVISOR and usuario.ativo):
        return False
    if novo_papel == Papel.SUPERVISOR and novo_ativo:
        return False
    outros = sessao.scalar(
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.papel == Papel.SUPERVISOR, Usuario.ativo, Usuario.id != usuario.id)
    )
    return outros == 0
