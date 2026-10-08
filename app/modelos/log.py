from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelos.base import Base
from app.modelos.usuario import Usuario

ROTULOS_ACAO = {
    "CRIAR": "Incluiu",
    "ALTERAR": "Alterou",
    "EXCLUIR": "Excluiu",
    "LOGIN": "Entrou no sistema",
    "LOGOUT": "Saiu do sistema",
    "LOGIN_FALHOU": "Tentativa de entrada com senha errada",
    "IMPORTAR_PLANO": "Importou o plano de contas",
    "IMPORTAR_HISTORICO": "Importou histórico de lançamentos",
    "IMPORTAR_EXTRATO": "Importou extrato bancário",
    "CLASSIFICAR": "Classificou os movimentos do extrato",
    "APRENDER": "Recalculou o aprendizado",
    "EXPORTAR": "Gerou o lanctos.txt",
    "REABRIR_EXPORTACAO": "Reabriu uma exportação",
    "BACKUP": "Fez backup",
    "BACKUP_FALHOU": "Backup falhou",
    "RESTAURAR_BACKUP": "Restaurou um backup",
}


class Log(Base):
    """Auditoria: quem fez o quê, quando, e como o registro estava antes e depois."""

    __tablename__ = "log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    acao: Mapped[str] = mapped_column(String(30))
    entidade: Mapped[str | None] = mapped_column(String(60))
    entidade_id: Mapped[str | None] = mapped_column(String(60))
    antes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    depois: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detalhe: Mapped[str | None] = mapped_column(Text)

    usuario: Mapped[Usuario | None] = relationship()

    @property
    def rotulo_acao(self) -> str:
        return ROTULOS_ACAO.get(self.acao, self.acao)

    def mudancas(self) -> list[tuple[str, Any, Any]]:
        """Lista (campo, antes, depois) para mostrar na tela."""
        antes, depois = self.antes or {}, self.depois or {}
        return [(campo, antes.get(campo), depois.get(campo)) for campo in {**antes, **depois}]
