"""Parte Python do INSTALAR.bat: cria o .env, as pastas de dados e liga o banco."""

from app.config import obter_config
from app.db import obter_engine
from scripts.banco_docker import preparar_banco
from scripts.comum import rodar
from scripts.criar_env import criar_env


def main() -> int:
    print("Preparando o arquivo de configuração (.env)...")
    if criar_env():
        print("  .env criado com senhas novas.")
    else:
        print("  .env já existia — mantido como está.")
    obter_config.cache_clear()
    obter_engine.cache_clear()

    config = obter_config()
    for pasta in (config.pasta_arquivos, config.pasta_backup):
        config.caminho(pasta).mkdir(parents=True, exist_ok=True)

    preparar_banco()
    return 0


if __name__ == "__main__":
    rodar(main)
