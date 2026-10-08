"""Parte Python do LIBERAR_REDE.bat e do FECHAR_REDE.bat: deixa (ou não) os outros computadores do escritório
usarem o sistema (§7.1). Libera a porta só para a rede PRIVADA no Firewall do Windows (nunca para a internet)
e troca o HOST do .env (0.0.0.0 = rede do escritório; 127.0.0.1 = só este computador).

Uso: .venv\\Scripts\\python -m scripts.rede liberar | fechar
"""

import argparse
import ctypes
import re
import socket
import subprocess
from pathlib import Path

from app.config import RAIZ, obter_config
from scripts.comum import ErroAmigavel, rodar

NOME_REGRA = "ZERA CONTABIL MAX"
SO_ESTE_COMPUTADOR = "127.0.0.1"
REDE_DO_ESCRITORIO = "0.0.0.0"
_HOST = re.compile(r"^\s*HOST\s*=.*$", re.MULTILINE)


def enderecos_da_rede() -> list[str]:
    """Os endereços deste computador na rede do escritório (ex.: 192.168.0.10), sem o 127.0.0.1."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos if not info[4][0].startswith("127.")})


def trocar_host(env: Path, host: str) -> None:
    """Muda só a linha HOST= do .env (o resto, inclusive as senhas, fica como está)."""
    texto = env.read_text(encoding="utf-8")
    if _HOST.search(texto):
        texto = _HOST.sub(f"HOST={host}", texto, count=1)
    else:
        texto = texto.rstrip("\n") + f"\nHOST={host}\n"
    env.write_text(texto, encoding="utf-8")


def comando_liberar(porta: int) -> list[str]:
    return [
        "netsh", "advfirewall", "firewall", "add", "rule", f"name={NOME_REGRA}", "dir=in", "action=allow",
        "protocol=TCP", f"localport={porta}", "profile=private",
    ]  # fmt: skip


def comando_fechar() -> list[str]:
    return ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={NOME_REGRA}"]


def _administrador() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:  # fora do Windows
        return False


def _netsh(comando: list[str]) -> bool:
    return subprocess.run(comando, capture_output=True, check=False).returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Libera ou fecha o acesso pela rede do escritório")
    parser.add_argument("acao", choices=("liberar", "fechar"))
    args = parser.parse_args(argv)
    env = RAIZ / ".env"
    if not env.exists():
        raise ErroAmigavel("O sistema ainda não foi instalado. Dê dois cliques no INSTALAR.bat primeiro.")
    if not _administrador():
        nome = "LIBERAR_REDE.bat" if args.acao == "liberar" else "FECHAR_REDE.bat"
        raise ErroAmigavel(
            f"Para mexer no Firewall do Windows: clique com o botão direito no {nome} e escolha "
            "“Executar como administrador”."
        )
    porta = obter_config().porta
    _netsh(comando_fechar())  # tira a regra antiga, se houver (não duplica)
    if args.acao == "fechar":
        trocar_host(env, SO_ESTE_COMPUTADOR)
        print("\nPronto: o sistema volta a abrir só neste computador.")
        print("Feche a janela do sistema (INICIAR.bat) e abra de novo.\n")
        return 0
    if not _netsh(comando_liberar(porta)):
        raise ErroAmigavel("O Windows não deixou liberar a porta no Firewall. Peça ajuda ao suporte de informática.")
    trocar_host(env, REDE_DO_ESCRITORIO)
    print(f"\nPronto: a porta {porta} foi liberada só para a rede PRIVADA do escritório (não para a internet).")
    print("Feche a janela do sistema (INICIAR.bat) e abra de novo. Nos outros computadores, abra no navegador:")
    for endereco in enderecos_da_rede() or ["(o endereço deste computador na rede)"]:
        print(f"    http://{endereco}:{porta}")
    print("\nSe não abrir: confira se a rede do Windows está como “Rede privada” (docs/acesso_pela_rede.md).\n")
    return 0


if __name__ == "__main__":
    rodar(main)
