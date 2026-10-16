"""Regras do escritório: “se a descrição do banco contém X → conta Y”, criadas na hora pela tela, sem esperar o
aprendizado. Valem antes do aprendizado (nome, CNPJ, palavra) e da regra do banco, e aprovam sozinhas (97%); só a
transferência entre contas da empresa vem antes. Ficam guardadas como `Padrao` tipo REGRA, origem USUARIO (o
aprendizado nunca mexe nelas)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import Empresa, MovimentoExtrato, Padrao
from app.servicos.aprendizado import normalizar_natureza
from app.servicos.competencia import Periodo
from app.servicos.contas_chave import achar_conta_analitica

SENTIDOS = {"": "entrada ou saída", "SAIDA": "só pagamentos (saídas)", "ENTRADA": "só recebimentos (entradas)"}


class ErroRegra(Exception):
    """Regra que não dá para criar — a mensagem diz o que fazer."""


def regras(sessao: Session, empresa: Empresa) -> list[Padrao]:
    return list(
        sessao.scalars(
            select(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.tipo == "REGRA").order_by(Padrao.nome)
        )
    )


def combina(regra: Padrao, movimento: MovimentoExtrato) -> bool:
    sentido = (regra.detalhes or {}).get("sentido") or ""
    if sentido and sentido != movimento.sentido:
        return False
    texto = f" {normalizar_natureza(movimento.historico + ' ' + (movimento.complemento or ''))} "
    return f" {regra.chave} " in texto


def criar_regra(
    sessao: Session, empresa: Empresa, texto: str, conta: str, sentido: str = "", natureza: str = ""
) -> Padrao:
    chave = normalizar_natureza(texto)
    if len(chave) < 3:
        raise ErroRegra(
            "Escreva o texto que aparece na descrição do banco, com pelo menos 3 letras (ex.: TARIFA, SABESP)."
        )
    if sentido not in SENTIDOS:
        raise ErroRegra("Escolha se a regra vale para entradas, saídas ou as duas.")
    escolhida, erro = achar_conta_analitica(sessao, empresa.id, conta)
    if erro:
        raise ErroRegra(erro)
    regra = sessao.scalar(
        select(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.tipo == "REGRA", Padrao.chave == chave)
    )
    if regra is None:
        regra = Padrao(empresa_id=empresa.id, tipo="REGRA", chave=chave)
        sessao.add(regra)
    regra.nome = " ".join(texto.upper().split())[:200]
    regra.conta_id, regra.conta = escolhida.id, escolhida
    regra.natureza = " ".join(natureza.upper().replace(";", ",").split())[:60] or None
    regra.detalhes = {"sentido": sentido}
    regra.origem, regra.ativo, regra.ambiguo = "USUARIO", True, False
    sessao.flush()
    return regra


def quantas_combinam(sessao: Session, empresa: Empresa, regra: Padrao, periodo: Periodo) -> int:
    inicio, fim = periodo.limites
    movimentos = sessao.scalars(
        select(MovimentoExtrato).where(
            MovimentoExtrato.empresa_id == empresa.id,
            MovimentoExtrato.data.between(inicio, fim),
            MovimentoExtrato.desdobrado.is_(False),
        )
    )
    return sum(combina(regra, movimento) for movimento in movimentos)
