"""Teste com a API REAL da Anthropic. Custa uma fração de centavo e só roda quando pedido:

    .venv\\Scripts\\python -m pytest -m ia_real -s

Usa a chave e os modelos do arquivo .env; sem chave, o teste é pulado.
"""

from dataclasses import replace

import pytest
from dotenv import dotenv_values

from app.config import RAIZ, Config
from app.ia.cliente import ClienteAnthropic
from app.ia.servico import PEDIDO_TESTE

pytestmark = pytest.mark.ia_real

_ENV = dotenv_values(RAIZ / ".env") if (RAIZ / ".env").exists() else {}
_PADRAO = Config(_env_file=None)
MODELOS = [
    _ENV.get("IA_MODELO_RAPIDO") or _PADRAO.ia_modelo_rapido,
    _ENV.get("IA_MODELO_FORTE") or _PADRAO.ia_modelo_forte,
]


@pytest.fixture(scope="module")
def cliente_real():
    chave = (_ENV.get("ANTHROPIC_API_KEY") or "").strip()
    if not chave:
        pytest.skip("Sem ANTHROPIC_API_KEY no arquivo .env")
    return ClienteAnthropic(chave, _PADRAO.ia_endereco)


@pytest.mark.parametrize("modelo", MODELOS)
def test_modelos_respondem_json_no_formato_pedido(cliente_real, modelo):
    # o modelo forte pensa antes de responder: precisa de mais espaço
    pedido = PEDIDO_TESTE if "haiku" in modelo else replace(PEDIDO_TESTE, max_tokens=4000, esforco="low")
    resposta = cliente_real.gerar(pedido, modelo)
    assert resposta.dados["ok"] is True
    assert resposta.dados["mensagem"]
    assert resposta.uso.entrada > 0 and resposta.uso.saida > 0
    print(f"\n{modelo} → {resposta.modelo}: {resposta.dados['mensagem']!r} | {resposta.uso}")
