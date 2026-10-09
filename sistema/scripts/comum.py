import sys
from collections.abc import Callable
from typing import NoReturn


class ErroAmigavel(Exception):
    """Erro com mensagem em português dizendo ao usuário o que fazer."""


def rodar(funcao: Callable[[], int]) -> NoReturn:
    try:
        codigo = funcao()
    except ErroAmigavel as erro:
        print(f"\n[ERRO] {erro}\n")
        codigo = 1
    except KeyboardInterrupt:
        codigo = 0
    sys.exit(codigo)
