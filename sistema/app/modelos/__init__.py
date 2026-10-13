"""Todos os modelos do banco. Importar daqui garante que o Alembic enxergue todas as tabelas."""

from app.modelos.aprendizado import LancamentoHistorico, Padrao
from app.modelos.base import Auditavel, Base
from app.modelos.conta_chave import ContaChave
from app.modelos.empresa import Empresa, Regime
from app.modelos.extrato import (
    SITUACOES_FORNECEDOR,
    STATUS_SUGESTAO,
    TIPOS_CONTA,
    ConferenciaDominio,
    ContaBancaria,
    Exportacao,
    Extrato,
    FornecedorACadastrar,
    ModeloPlanilha,
    MovimentoExtrato,
    Sugestao,
)
from app.modelos.ia import ChamadaIA
from app.modelos.importacao import ArquivoOriginal, ArquivoPasta, Importacao
from app.modelos.log import Log
from app.modelos.plano import ContaContabil
from app.modelos.usuario import Papel, Usuario

__all__ = [
    "ArquivoOriginal",
    "ArquivoPasta",
    "Auditavel",
    "Base",
    "ChamadaIA",
    "ConferenciaDominio",
    "ContaBancaria",
    "ContaChave",
    "ContaContabil",
    "Empresa",
    "Exportacao",
    "Extrato",
    "FornecedorACadastrar",
    "Importacao",
    "LancamentoHistorico",
    "Log",
    "ModeloPlanilha",
    "MovimentoExtrato",
    "Padrao",
    "Papel",
    "Regime",
    "SITUACOES_FORNECEDOR",
    "STATUS_SUGESTAO",
    "Sugestao",
    "TIPOS_CONTA",
    "Usuario",
]
