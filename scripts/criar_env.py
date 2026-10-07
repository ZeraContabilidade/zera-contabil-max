"""Cria o arquivo .env a partir do .env.example, gerando senhas aleatórias.
Em atualizações, acrescenta ao .env só as configurações novas (o que já existe nunca é alterado)."""

import re
import secrets
from pathlib import Path

from app.config import RAIZ
from app.servicos.competencia import hoje

MARCADOR = "GERAR_AUTOMATICAMENTE"
_CHAVE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")


def _preencher(linha: str) -> str:
    while MARCADOR in linha:
        linha = linha.replace(MARCADOR, secrets.token_urlsafe(24), 1)
    return linha


def criar_env(modelo: Path = RAIZ / ".env.example", destino: Path = RAIZ / ".env") -> bool:
    """Devolve True se criou o .env. Um .env que já existe nunca é alterado."""
    if destino.exists():
        return False
    linhas = [_preencher(linha) for linha in modelo.read_text(encoding="utf-8").splitlines(keepends=True)]
    destino.write_text("".join(linhas), encoding="utf-8")
    return True


def completar_env(modelo: Path = RAIZ / ".env.example", destino: Path = RAIZ / ".env") -> list[str]:
    """Acrescenta ao .env as configurações que o modelo tem e o .env ainda não. Devolve os nomes."""
    atuais = {m.group(1) for linha in destino.read_text(encoding="utf-8").splitlines() if (m := _CHAVE.match(linha))}
    novas, bloco, comentarios = [], [], []
    for linha in modelo.read_text(encoding="utf-8").splitlines():
        if linha.strip().startswith("#"):
            comentarios.append(linha)
            continue
        if (m := _CHAVE.match(linha)) and m.group(1) not in atuais:
            bloco += comentarios + [_preencher(linha)]
            novas.append(m.group(1))
        comentarios = [] if linha.strip() == "" or m else comentarios
    if novas:
        texto = destino.read_text(encoding="utf-8").rstrip("\n")
        cabecalho = f"\n\n# --- acrescentado na atualização de {hoje().strftime('%d/%m/%Y')} ---\n"
        destino.write_text(texto + cabecalho + "\n".join(bloco) + "\n", encoding="utf-8")
    return novas
