from pathlib import Path

from app.config import RAIZ, Config


def config_teste(**valores) -> Config:
    # ignora o .env e o DATABASE_URL do banco de teste (conftest); valores passados aqui têm prioridade
    return Config(_env_file=None, **{"database_url": "", **valores})


def test_url_do_banco_montada_pelas_partes_com_senha_especial():
    config = config_teste(postgres_password="a@b/c:d", postgres_port=5433)
    assert config.url_banco() == "postgresql+psycopg://zera:a%40b%2Fc%3Ad@127.0.0.1:5433/zera_contabil_max"


def test_database_url_tem_prioridade_para_a_nuvem():
    config = config_teste(database_url="postgresql+psycopg://u:s@nuvem:5432/b", postgres_password="x")
    assert config.url_banco() == "postgresql+psycopg://u:s@nuvem:5432/b"


def test_pasta_relativa_fica_dentro_do_sistema_e_absoluta_e_mantida():
    config = config_teste()
    assert config.caminho(Path("dados/backups")) == RAIZ / "dados" / "backups"
    absoluta = RAIZ / "qualquer"
    assert config.caminho(absoluta) == absoluta
