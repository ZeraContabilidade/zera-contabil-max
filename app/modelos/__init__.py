"""Todos os modelos do banco. Importar daqui garante que o Alembic enxergue todas as tabelas."""

from app.modelos.base import Auditavel, Base
from app.modelos.log import Log
from app.modelos.usuario import Papel, Usuario

__all__ = ["Auditavel", "Base", "Log", "Papel", "Usuario"]
