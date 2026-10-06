"""Log de auditoria automático.

Toda inclusão, alteração ou exclusão de um modelo `Auditavel` gera uma linha na tabela `log`
(quem, quando, antes e depois), sem que cada tela precise lembrar de registrar.
Quem fez a alteração vem de `sessao.info["usuario_id"]`, preenchido no login (app/auth.py).
"""

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import event, insert, inspect
from sqlalchemy.orm import Session

from app.modelos import Auditavel, Log


def _para_json(valor: Any) -> Any:
    if valor is None or isinstance(valor, str | int | float | bool):
        return valor
    if isinstance(valor, enum.Enum):
        return valor.value
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    return str(valor)


def _mostrar(obj: Auditavel, campo: str, valor: Any) -> Any:
    return "***" if campo in obj.campos_sigilosos else _para_json(valor)


def _campos(obj: Auditavel) -> list[str]:
    estado = inspect(obj)
    return [
        atributo.key
        for atributo in estado.mapper.column_attrs
        if atributo.key not in obj.campos_nao_auditados and atributo.key not in estado.unloaded
    ]


def _retrato(obj: Auditavel) -> dict[str, Any]:
    return {campo: _mostrar(obj, campo, getattr(obj, campo)) for campo in _campos(obj)}


def _diferencas(obj: Auditavel) -> tuple[dict[str, Any], dict[str, Any]]:
    estado = inspect(obj)
    antes, depois = {}, {}
    for campo in _campos(obj):
        historico = estado.attrs[campo].history
        if historico.has_changes():
            antes[campo] = _mostrar(obj, campo, historico.deleted[0] if historico.deleted else None)
            depois[campo] = _mostrar(obj, campo, historico.added[0] if historico.added else None)
    return antes, depois


def _linha(sessao: Session, acao: str, obj: Auditavel, antes=None, depois=None) -> dict[str, Any]:
    # identity ainda não existe para objetos novos em after_flush; a chave primária já foi preenchida
    chave = inspect(obj).mapper.primary_key_from_instance(obj)
    return {
        "usuario_id": sessao.info.get("usuario_id"),
        "acao": acao,
        "entidade": obj.__tablename__,
        "entidade_id": "-".join(str(parte) for parte in chave),
        "antes": antes,
        "depois": depois,
    }


@event.listens_for(Session, "after_flush")
def _auditar(sessao: Session, _contexto) -> None:
    # em after_flush as listas new/dirty/deleted e o histórico ainda mostram o que foi gravado
    linhas = []
    for obj in sessao.new:
        if isinstance(obj, Auditavel):
            linhas.append(_linha(sessao, "CRIAR", obj, depois=_retrato(obj)))
    for obj in sessao.dirty:
        if isinstance(obj, Auditavel):
            antes, depois = _diferencas(obj)
            if depois:
                linhas.append(_linha(sessao, "ALTERAR", obj, antes=antes, depois=depois))
    for obj in sessao.deleted:
        if isinstance(obj, Auditavel):
            linhas.append(_linha(sessao, "EXCLUIR", obj, antes=_retrato(obj)))
    if linhas:
        sessao.connection().execute(insert(Log.__table__), linhas)


def registrar_evento(sessao: Session, acao: str, usuario_id: int | None = None, detalhe: str | None = None):
    """Eventos que não são alteração de registro (entrada, saída, senha errada...)."""
    sessao.add(Log(acao=acao, usuario_id=usuario_id or sessao.info.get("usuario_id"), detalhe=detalhe))
