"""Porta de entrada da IA para o resto do sistema (§6.4).

`chamar_ia` confere se pode chamar (chave no .env, IA ligada na empresa, limite mensal), chama,
registra tokens e custo em `chamada_ia` — inclusive quando dá erro — e devolve os dados.
Se a IA não puder ajudar, levanta `ErroIA` (ou `IAIndisponivel`) e quem chamou segue só com
regras e aprendizado.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import obter_config
from app.db import fabrica_sessoes
from app.ia.cliente import (
    RESPOSTAS_DEMONSTRACAO,
    ClienteAnthropic,
    ClienteFalso,
    ClienteIA,
    ErroIA,
    PedidoIA,
    RespostaIA,
    UsoTokens,
)
from app.ia.precos import estimar_custo
from app.modelos import ChamadaIA, Empresa, Usuario

FUSO = ZoneInfo("America/Sao_Paulo")


class IAIndisponivel(ErroIA):
    """A IA nem foi chamada: está desligada, sem chave ou o limite do mês foi atingido."""


@lru_cache
def obter_cliente() -> ClienteIA | None:
    config = obter_config()
    if config.ia_simulada:
        return ClienteFalso(RESPOSTAS_DEMONSTRACAO)
    chave = config.anthropic_api_key.strip()
    return ClienteAnthropic(chave, config.ia_endereco) if chave else None


def dolar(valor: Decimal, casas: int = 2) -> str:
    """Decimal('12.5') → 'US$ 12,50'."""
    return "US$ " + f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def inicio_do_mes() -> datetime:
    agora = datetime.now(FUSO)
    return agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def gasto_do_mes(sessao: Session, empresa: Empresa | None = None) -> Decimal:
    consulta = select(func.coalesce(func.sum(ChamadaIA.custo_usd), 0)).where(ChamadaIA.quando >= inicio_do_mes())
    if empresa is not None:
        consulta = consulta.where(ChamadaIA.empresa_id == empresa.id)
    return Decimal(sessao.scalar(consulta))


@dataclass
class SituacaoIA:
    disponivel: bool
    motivo: str
    simulada: bool
    gasto_mes: Decimal
    limite: Decimal
    modelo_rapido: str
    modelo_forte: str

    @property
    def percentual(self) -> int:
        return min(100, int(self.gasto_mes * 100 / self.limite)) if self.limite else 100


def situacao_ia(sessao: Session) -> SituacaoIA:
    config = obter_config()
    gasto = gasto_do_mes(sessao)
    if obter_cliente() is None:
        disponivel, motivo = False, "Desligada: falta a chave da IA. Para ligar, rode o Ferramentas\\CONFIGURAR_IA.bat."
    elif gasto >= config.ia_limite_mensal_usd:
        disponivel, motivo = False, "Pausada: o limite de gasto deste mês foi atingido."
    else:
        disponivel, motivo = True, "Pronta para uso."
    return SituacaoIA(
        disponivel,
        motivo,
        config.ia_simulada,
        gasto,
        config.ia_limite_mensal_usd,
        config.ia_modelo_rapido,
        config.ia_modelo_forte,
    )


def _conferir_limites(sessao: Session, empresa: Empresa | None) -> None:
    limite = obter_config().ia_limite_mensal_usd
    gasto = gasto_do_mes(sessao)
    if gasto >= limite:
        raise IAIndisponivel(
            f"O limite mensal de gasto com IA ({dolar(limite)}) foi atingido: {dolar(gasto)} neste mês. "
            "A IA volta no mês que vem — ou aumente IA_LIMITE_MENSAL_USD no arquivo .env."
        )
    if empresa is not None and empresa.ia_limite_mensal_usd is not None:
        gasto_empresa = gasto_do_mes(sessao, empresa)
        if gasto_empresa >= empresa.ia_limite_mensal_usd:
            raise IAIndisponivel(
                f"O limite mensal de IA de {empresa.nome} "
                f"({dolar(empresa.ia_limite_mensal_usd)}) foi atingido. "
                "Aumente no cadastro da empresa ou espere o mês que vem."
            )


def custo_estimado(modelo: str, uso: UsoTokens) -> Decimal:
    """No modo simulado nada é cobrado: custo zero."""
    if obter_config().ia_simulada:
        return Decimal("0")
    return estimar_custo(modelo, uso.entrada, uso.saida, uso.cache_escrita, uso.cache_leitura)


def _registrar(
    pedido: PedidoIA,
    modelo: str,
    empresa: Empresa | None,
    usuario: Usuario | None,
    inicio: float,
    uso: UsoTokens | None,
    resposta: RespostaIA | None = None,
    erro: str | None = None,
) -> ChamadaIA:
    """Grava numa sessão própria: o gasto fica registrado mesmo se a tela que chamou desistir depois."""
    uso = uso or UsoTokens()
    chamada = ChamadaIA(
        empresa_id=empresa.id if empresa else None,
        usuario_id=usuario.id if usuario else None,
        finalidade=pedido.finalidade[:40],
        modelo=modelo[:60],
        sucesso=erro is None,
        erro=erro,
        tokens_entrada=uso.entrada,
        tokens_saida=uso.saida,
        tokens_cache_escrita=uso.cache_escrita,
        tokens_cache_leitura=uso.cache_leitura,
        custo_usd=custo_estimado(modelo, uso),
        duracao_ms=int((time.monotonic() - inicio) * 1000),
        request_id=resposta.request_id if resposta else None,
        entrada_resumo=pedido.pergunta[:2000],
        resposta=resposta.dados if resposta else None,
    )
    with fabrica_sessoes()() as registro:
        registro.add(chamada)
        registro.commit()
    return chamada


def chamar_ia(
    sessao: Session, pedido: PedidoIA, empresa: Empresa | None = None, usuario: Usuario | None = None
) -> RespostaIA:
    cliente = obter_cliente()
    if cliente is None:
        raise IAIndisponivel("A IA está desligada: falta a chave. Para ligar, rode o Ferramentas\\CONFIGURAR_IA.bat.")
    if empresa is not None and not empresa.ia_ligada:
        raise IAIndisponivel(f"A IA está desligada para {empresa.nome} (veja o cadastro da empresa).")
    _conferir_limites(sessao, empresa)

    config = obter_config()
    modelo = config.ia_modelo_forte if pedido.forte else config.ia_modelo_rapido
    inicio = time.monotonic()
    try:
        resposta = cliente.gerar(pedido, modelo)
    except ErroIA as erro:
        _registrar(pedido, erro.modelo or modelo, empresa, usuario, inicio, erro.uso, erro=str(erro))
        raise
    _registrar(pedido, resposta.modelo, empresa, usuario, inicio, resposta.uso, resposta=resposta)
    return resposta


PEDIDO_TESTE = PedidoIA(
    finalidade="teste",
    instrucoes="Você está testando a conexão do sistema ZERA CONTÁBIL MAX. Responda somente o JSON pedido.",
    pergunta="Responda ok = true e, em mensagem, uma saudação curta em português do Brasil.",
    esquema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}, "mensagem": {"type": "string"}},
        "required": ["ok", "mensagem"],
        "additionalProperties": False,
    },
    max_tokens=300,
)


def testar_conexao(sessao: Session, usuario: Usuario | None) -> RespostaIA:
    """Chamada mínima ao modelo rápido (custa uma fração de centavo) para conferir chave e créditos."""
    return chamar_ia(sessao, PEDIDO_TESTE, usuario=usuario)
