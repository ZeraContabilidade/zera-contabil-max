"""Todos os modelos do banco. Importar daqui garante que o Alembic enxergue todas as tabelas."""

from app.modelos.base import Auditavel, Base
from app.modelos.conta_chave import ContaChave
from app.modelos.empresa import Empresa, Regime
from app.modelos.ia import ChamadaIA
from app.modelos.importacao import ArquivoOriginal, Importacao
from app.modelos.log import Log
from app.modelos.plano import ContaContabil
from app.modelos.usuario import Papel, Usuario

__all__ = [
    "ArquivoOriginal",
    "Auditavel",
    "Base",
    "ChamadaIA",
    "ContaChave",
    "ContaContabil",
    "Empresa",
    "Importacao",
    "Log",
    "Papel",
    "Regime",
    "Usuario",
]
