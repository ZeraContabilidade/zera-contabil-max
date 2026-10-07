"""Liga o Docker Desktop (se preciso), sobe o PostgreSQL e espera ele aceitar conexões."""

import os
import subprocess
import time
from pathlib import Path

from app.config import RAIZ
from app.db import aplicar_migracoes, banco_disponivel
from scripts.comum import ErroAmigavel


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], cwd=RAIZ, capture_output=True, text=True, timeout=timeout)


def docker_rodando() -> bool:
    try:
        return _docker("info", timeout=20).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _executavel_docker_desktop() -> Path | None:
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if base:
            exe = Path(base) / "Docker" / "Docker" / "Docker Desktop.exe"
            if exe.exists():
                return exe
    return None


def ligar_docker(espera_segundos: int = 180) -> None:
    if docker_rodando():
        return
    exe = _executavel_docker_desktop()
    if exe is None:
        raise ErroAmigavel(
            "O Docker não está rodando e não encontrei o Docker Desktop. "
            "Abra o Docker Desktop pelo menu Iniciar e tente de novo."
        )
    print("Abrindo o Docker Desktop (pode levar 1 ou 2 minutos)...")
    subprocess.Popen([str(exe)])
    limite = time.monotonic() + espera_segundos
    while time.monotonic() < limite:
        time.sleep(3)
        if docker_rodando():
            return
    raise ErroAmigavel("O Docker Desktop não terminou de abrir. Espere aparecer 'Engine running' nele e tente de novo.")


def subir_banco() -> None:
    # na primeira vez o Docker baixa a imagem do PostgreSQL, por isso o tempo longo
    resultado = _docker("compose", "up", "-d", "banco", timeout=600)
    if resultado.returncode != 0:
        raise ErroAmigavel("Não consegui ligar o banco de dados no Docker.\n" + resultado.stderr.strip())


def esperar_banco(espera_segundos: int = 90) -> None:
    limite = time.monotonic() + espera_segundos
    while time.monotonic() < limite:
        if banco_disponivel():
            return
        time.sleep(2)
    raise ErroAmigavel(
        "O banco de dados não respondeu. Veja se o Docker Desktop está aberto "
        "e se a senha no arquivo .env não foi alterada depois da instalação."
    )


def preparar_banco() -> None:
    if not banco_disponivel():  # no dia a dia o banco já sobe junto com o Docker Desktop
        print("Verificando o Docker...")
        ligar_docker()
        print("Ligando o banco de dados...")
        subir_banco()
        esperar_banco()
    aplicar_migracoes()  # cria ou atualiza as tabelas para esta versão do sistema
    print("Banco de dados pronto.")
