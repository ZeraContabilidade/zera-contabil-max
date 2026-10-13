"""Mesa de trabalho: saudação, próximo passo sugerido e o sistema instalável como aplicativo."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.modelos import Empresa
from app.rotas.empresas import proximo_passo
from app.web import FUSO, saudacao
from tests.conftest import entrar


def test_saudacao_pelo_relogio():
    def as_(hora: int) -> str:
        return saudacao(datetime(2026, 10, 13, hora, 0, tzinfo=FUSO))

    assert (as_(9), as_(13), as_(19), as_(3)) == ("Bom dia", "Boa tarde", "Boa noite", "Boa noite")


def _linha(empresa_id, responsavel_id, feitas, ativa=True, concluida=False):
    etapas = [SimpleNamespace(situacao="feita")] * feitas + [SimpleNamespace(situacao="atual")]
    empresa = SimpleNamespace(id=empresa_id, responsavel_id=responsavel_id, ativa=ativa)
    return {"empresa": empresa, "etapas": etapas, "atual": None if concluida else etapas[-1]}


def test_proximo_passo_prefere_as_minhas_e_a_mais_adiantada():
    ana = SimpleNamespace(id=1)
    linhas = [_linha(10, 2, 4), _linha(11, 1, 1), _linha(12, 1, 3), _linha(13, 1, 4, concluida=True)]
    assert proximo_passo(linhas, ana)["empresa"].id == 12  # das minhas, a mais perto de terminar
    assert proximo_passo(linhas, SimpleNamespace(id=9))["empresa"].id == 10  # sem nenhuma: a mais adiantada de todas
    assert proximo_passo([_linha(14, 1, 2, ativa=False), linhas[3]], ana) is None


@pytest.mark.banco
def test_mesa_de_trabalho_cumprimenta_e_sugere(cliente, criar_usuario, sessao):
    ana = criar_usuario("ana", nome="Ana Supervisora")
    entrar(cliente, "ana")
    sessao.add_all([Empresa(codigo_dominio=230, nome_curto="Casa Criança", responsavel_id=ana.id),
                    Empresa(codigo_dominio=410, nome_curto="Padaria")])  # fmt: skip
    sessao.commit()
    tela = cliente.get("/").text
    assert f"{saudacao()}, Ana · mesa de trabalho" in tela
    assert "Próximo passo sugerido" in tela and "Casa Criança" in tela.split("Próximo passo sugerido")[1][:300]


@pytest.mark.banco
def test_instalavel_como_aplicativo(cliente, criar_usuario):
    criar_usuario("ana")
    entrar(cliente, "ana")
    assert 'rel="manifest"' in cliente.get("/").text
    manifesto = cliente.get("/static/manifest.json").json()
    assert manifesto["name"] == "ZERA CONTÁBIL MAX" and manifesto["display"] == "standalone"
    for icone in manifesto["icons"]:
        assert cliente.get(icone["src"]).status_code == 200
