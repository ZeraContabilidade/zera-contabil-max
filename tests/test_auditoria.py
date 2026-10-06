import pytest
from sqlalchemy import select

from app.auth import gerar_hash
from app.modelos import Log, Papel, Usuario

pytestmark = pytest.mark.banco


def test_auditoria_vale_tambem_fora_das_telas(sessao):
    """Rotinas sem tela (importações, scripts) também deixam rastro no log."""
    sessao.add(Usuario(nome="Rotina", login="rotina", senha_hash=gerar_hash("x" * 8), papel=Papel.CONTADOR))
    sessao.commit()
    registro = sessao.scalar(select(Log).where(Log.acao == "CRIAR"))
    assert registro.usuario_id is None  # sem login: aparece como "Sistema"
    assert registro.depois["login"] == "rotina"


def test_exclusao_guarda_como_estava(sessao):
    usuario = Usuario(nome="Temp", login="temp", senha_hash=gerar_hash("x" * 8), papel=Papel.ASSISTENTE)
    sessao.add(usuario)
    sessao.commit()
    sessao.delete(usuario)
    sessao.commit()
    registro = sessao.scalar(select(Log).where(Log.acao == "EXCLUIR"))
    assert registro.antes["nome"] == "Temp"
    assert registro.depois is None
