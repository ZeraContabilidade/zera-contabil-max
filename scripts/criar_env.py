"""Cria o arquivo .env a partir do .env.example, gerando senhas aleatórias."""

import secrets
from pathlib import Path

from app.config import RAIZ

MARCADOR = "GERAR_AUTOMATICAMENTE"


def criar_env(modelo: Path = RAIZ / ".env.example", destino: Path = RAIZ / ".env") -> bool:
    """Devolve True se criou o .env. Um .env que já existe nunca é alterado."""
    if destino.exists():
        return False
    linhas = []
    for linha in modelo.read_text(encoding="utf-8").splitlines(keepends=True):
        while MARCADOR in linha:
            linha = linha.replace(MARCADOR, secrets.token_urlsafe(24), 1)
        linhas.append(linha)
    destino.write_text("".join(linhas), encoding="utf-8")
    return True
