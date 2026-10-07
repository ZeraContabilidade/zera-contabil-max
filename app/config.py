"""Configurações do sistema, lidas do arquivo .env (nenhum caminho fixo no código)."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

RAIZ = Path(__file__).resolve().parent.parent


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=RAIZ / ".env", env_file_encoding="utf-8", extra="ignore")

    nome_sistema: str = "ZERA CONTÁBIL MAX"

    # Banco de dados: DATABASE_URL (nuvem) tem prioridade sobre as partes POSTGRES_* (Docker local)
    database_url: str = ""
    postgres_user: str = "zera"
    postgres_password: str = ""
    postgres_db: str = "zera_contabil_max"
    postgres_host: str = "127.0.0.1"  # "localhost" no Windows tenta IPv6 antes e atrasa ~2 s
    postgres_port: int = 5433

    # Pastas: relativas à raiz do sistema ou caminho completo
    pasta_arquivos: Path = Path("dados/arquivos")
    pasta_backup: Path = Path("dados/backups")
    pasta_backup_nuvem: str = ""  # Google Drive; em branco = encontra sozinho; "NAO" = sem cópia na nuvem

    # Servidor web
    host: str = "127.0.0.1"
    porta: int = 8000
    chave_sessao: str = ""

    # IA (API da Anthropic). Sem chave, o sistema funciona só com regras e aprendizado.
    anthropic_api_key: str = ""
    ia_endereco: str = "https://api.anthropic.com"  # fixo: ignora ANTHROPIC_BASE_URL de outros programas
    ia_modelo_rapido: str = "claude-haiku-4-5"  # lotes de históricos e classificação
    ia_modelo_forte: str = "claude-sonnet-5-5"  # auto-configuração, PDF e casos difíceis
    ia_limite_mensal_usd: Decimal = Decimal("20")
    ia_simulada: bool = False  # True = respostas de demonstração, sem internet e sem custo

    def url_banco(self) -> str:
        if self.database_url:
            return self.database_url
        url = URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
        return url.render_as_string(hide_password=False)

    def caminho(self, pasta: Path) -> Path:
        """Converte uma pasta do .env em caminho completo (relativo à raiz do sistema)."""
        return pasta if pasta.is_absolute() else RAIZ / pasta


@lru_cache
def obter_config() -> Config:
    return Config()
