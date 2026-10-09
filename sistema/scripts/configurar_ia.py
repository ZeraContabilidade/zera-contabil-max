"""Parte Python do Ferramentas\\CONFIGURAR_IA.bat: guarda a chave da API da Anthropic no sistema\\.env.

A chave é digitada (ou colada) sem aparecer na tela e nunca é mostrada nem registrada no Log.
Uso: CONFIGURAR_IA.bat
"""

import getpass
import re

from app.config import ARQUIVO_ENV
from scripts.comum import ErroAmigavel, rodar

_LINHA = re.compile(r"^\s*ANTHROPIC_API_KEY\s*=.*$", re.MULTILINE)
_CHAVE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")


def gravar_chave(texto_env: str, chave: str) -> str:
    """Troca (ou acrescenta) só a linha ANTHROPIC_API_KEY=; o resto do .env fica como está."""
    linha = f"ANTHROPIC_API_KEY={chave}"
    if _LINHA.search(texto_env):
        return _LINHA.sub(lambda _: linha, texto_env, count=1)
    return texto_env.rstrip("\n") + f"\n{linha}\n"


def chave_valida(chave: str) -> bool:
    return bool(_CHAVE.match(chave))


def main() -> int:
    if not ARQUIVO_ENV.exists():
        raise ErroAmigavel("O sistema ainda não foi instalado. Na pasta Ferramentas, dê dois cliques no INSTALAR.bat.")
    print("\nCole a chave da API da Anthropic (criada em console.anthropic.com) e tecle Enter.")
    print("Por segurança, ela NÃO aparece enquanto você cola. Para desligar a IA, digite APAGAR.\n")
    chave = "".join(getpass.getpass("Chave: ").split())
    if chave.upper() == "APAGAR":
        chave = ""
    elif not chave_valida(chave):
        raise ErroAmigavel(
            "Isso não parece uma chave da Anthropic (ela começa com sk-ant-). Copie de novo e tente outra vez."
        )
    ARQUIVO_ENV.write_text(gravar_chave(ARQUIVO_ENV.read_text(encoding="utf-8"), chave), encoding="utf-8")
    if chave:
        print("\nPronto: chave guardada. Feche a janela do sistema (INICIAR.bat) e abra de novo;")
        print("depois, no menu IA, clique em “Testar conexão com a IA”.\n")
    else:
        print("\nPronto: a IA foi desligada (o sistema continua com as regras e o aprendizado).\n")
    return 0


if __name__ == "__main__":
    rodar(main)
