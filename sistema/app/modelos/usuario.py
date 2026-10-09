import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.modelos.base import Auditavel, Base


class Papel(enum.StrEnum):
    ASSISTENTE = "ASSISTENTE"
    CONTADOR = "CONTADOR"
    SUPERVISOR = "SUPERVISOR"

    @property
    def rotulo(self) -> str:
        return self.value.capitalize()


class Usuario(Auditavel, Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    login: Mapped[str] = mapped_column(String(120), unique=True)  # sempre minúsculo
    email: Mapped[str | None] = mapped_column(String(200), unique=True)  # sempre minúsculo
    senha_hash: Mapped[str] = mapped_column(String(255))
    papel: Mapped[Papel] = mapped_column(
        Enum(Papel, native_enum=False, length=20, create_constraint=True, name="papel")
    )
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ultimo_acesso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campos_sigilosos = ("senha_hash",)
    campos_nao_auditados = ("ultimo_acesso",)

    @property
    def e_supervisor(self) -> bool:
        return self.papel == Papel.SUPERVISOR
