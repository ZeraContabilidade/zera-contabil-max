"""Parte Python do Ferramentas\\INSTALAR.bat: cria o .env, as pastas de dados, liga o banco e deixa a pasta limpa."""

import subprocess
import sys

from app.config import RAIZ, obter_config
from app.db import fabrica_sessoes, obter_engine
from scripts.banco_docker import preparar_banco
from scripts.comum import rodar
from scripts.criar_env import completar_env, criar_env

# pastas técnicas da pasta principal: ocultas no Explorador (só pastas: arquivo oculto o Windows não deixa regravar)
PASTAS_TECNICAS = (".git", ".venv", ".claude", ".pytest_cache", ".ruff_cache", ".playwright-mcp")


def ocultar_pastas_tecnicas() -> list[str]:
    """Marca as pastas técnicas como ocultas (Windows). Devolve as que foram marcadas."""
    if sys.platform != "win32":
        return []
    ocultas = []
    for nome in PASTAS_TECNICAS:
        pasta = RAIZ / nome
        if pasta.is_dir():
            subprocess.run(["attrib", "+h", str(pasta)], capture_output=True, check=False)
            ocultas.append(nome)
    return ocultas


def main() -> int:
    print("Preparando o arquivo de configuração (sistema\\.env)...")
    if criar_env():
        print("  .env criado com senhas novas.")
    elif novas := completar_env():
        print(f"  .env mantido; acrescentadas as configurações novas: {', '.join(novas)}.")
    else:
        print("  .env já existia — mantido como está.")
    obter_config.cache_clear()
    obter_engine.cache_clear()
    fabrica_sessoes.cache_clear()

    config = obter_config()
    for pasta in (config.pasta_arquivos, config.pasta_backup):
        config.caminho(pasta).mkdir(parents=True, exist_ok=True)

    preparar_banco()
    ocultar_pastas_tecnicas()
    return 0


if __name__ == "__main__":
    rodar(main)
