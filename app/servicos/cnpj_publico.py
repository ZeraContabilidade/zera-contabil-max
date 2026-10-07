"""Consulta pública do CNPJ (BrasilAPI) para preencher o cadastro sozinho.

Opcional: sem internet ou com a BrasilAPI fora do ar, devolve None e o sistema segue normalmente.
Envia só o CNPJ (dado público da empresa).
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.modelos.empresa import Regime
from app.servicos.competencia import hoje

ENDERECO = "https://brasilapi.com.br/api/cnpj/v1/{}"


@dataclass
class DadosPublicos:
    razao_social: str
    nome_fantasia: str | None
    regime: Regime | None
    resumo: dict[str, Any] = field(default_factory=dict)


def _buscar_http(cnpj: str) -> dict[str, Any] | None:
    pedido = urllib.request.Request(ENDERECO.format(cnpj), headers={"User-Agent": "ZeraContabilMax/1.0"})
    try:
        with urllib.request.urlopen(pedido, timeout=8) as resposta:
            return json.load(resposta)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def regime_pelos_dados(dados: dict[str, Any]) -> Regime | None:
    if dados.get("opcao_pelo_mei"):
        return Regime.MEI
    if dados.get("opcao_pelo_simples"):
        return Regime.SIMPLES
    anos = [r for r in dados.get("regime_tributario") or [] if isinstance(r, dict)]
    if anos:
        forma = str(max(anos, key=lambda r: r.get("ano") or 0).get("forma_de_tributacao") or "").upper()
        if "PRESUMIDO" in forma:
            return Regime.PRESUMIDO
        if "REAL" in forma:
            return Regime.REAL
        if "IMUNE" in forma or "ISENTA" in forma:
            return Regime.TERCEIRO_SETOR
    # natureza jurídica 3xx-x = entidades sem fins lucrativos (associações, fundações...)
    if str(dados.get("codigo_natureza_juridica") or "").startswith("3"):
        return Regime.TERCEIRO_SETOR
    return None


def consultar_cnpj(cnpj: str) -> DadosPublicos | None:
    dados = _buscar_http(cnpj)
    if not dados or not dados.get("razao_social"):
        return None
    natureza = " - ".join(str(p) for p in (dados.get("codigo_natureza_juridica"), dados.get("natureza_juridica")) if p)
    municipio = "/".join(str(p) for p in (dados.get("municipio"), dados.get("uf")) if p)
    resumo = {
        "natureza_juridica": natureza or None,
        "atividade": dados.get("cnae_fiscal_descricao"),
        "municipio": municipio or None,
        "situacao": dados.get("descricao_situacao_cadastral"),
        "consultado_em": hoje().isoformat(),
    }
    return DadosPublicos(
        razao_social=str(dados["razao_social"]).strip(),
        nome_fantasia=(str(dados.get("nome_fantasia") or "").strip() or None),
        regime=regime_pelos_dados(dados),
        resumo={chave: valor for chave, valor in resumo.items() if valor},
    )
