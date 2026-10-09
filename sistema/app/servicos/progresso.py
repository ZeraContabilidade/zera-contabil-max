"""Barra de progresso do mês (ou do período) de cada empresa: Plano → Aprendizado → Extrato → Revisão → Exportado."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import Empresa, Padrao
from app.servicos.competencia import Periodo
from app.servicos.exportacao import situacao_do_mes
from app.servicos.extratos import contar_movimentos_do_mes
from app.servicos.plano import contar_contas
from app.servicos.revisao import contagem_do_mes

ETAPAS = (
    ("plano", "Plano"),
    ("aprendizado", "Aprendizado"),
    ("extrato", "Extrato"),
    ("revisao", "Revisão"),
    ("exportado", "Exportado"),
)


@dataclass(frozen=True)
class Etapa:
    chave: str
    nome: str
    situacao: str  # "feita", "atual" (a próxima a fazer) ou "pendente"
    detalhe: str = ""


def _concluidas(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> dict[str, str]:
    """Etapas já feitas → detalhe. Cada parte do sistema acrescenta a sua conferência aqui:
    plano (1.4), aprendizado (1.7), extrato (2.1), revisão (2.8) e exportado (3.1)."""
    feitas = {}
    total_contas, _ = contar_contas(sessao, empresa)
    if total_contas:
        feitas["plano"] = f"{total_contas:,} contas".replace(",", ".")
    padroes = sessao.scalar(
        select(func.count()).select_from(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.ativo)
    )
    if padroes:
        feitas["aprendizado"] = f"{padroes:,} padrões".replace(",", ".")
    if movimentos := contar_movimentos_do_mes(sessao, empresa, competencia):
        feitas["extrato"] = f"{movimentos:,} movimentos".replace(",", ".")
        contagem = contagem_do_mes(sessao, empresa, competencia)
        if contagem.total and not (contagem.amarela or contagem.vermelha):
            feitas["revisao"] = f"{contagem.verde:,} aprovados".replace(",", ".")
        exportadas, faltam = situacao_do_mes(sessao, empresa, competencia)
        if exportadas and not faltam:  # tudo o que foi aprovado já está num lanctos.txt
            feitas["exportado"] = f"{exportadas:,} lançamentos".replace(",", ".")
    return feitas


def progresso_do_mes(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> list[Etapa]:
    feitas = _concluidas(sessao, empresa, competencia)
    etapas, achou_atual = [], False
    for chave, nome in ETAPAS:
        if chave in feitas:
            etapas.append(Etapa(chave, nome, "feita", feitas[chave]))
        elif not achou_atual:
            etapas.append(Etapa(chave, nome, "atual"))
            achou_atual = True
        else:
            etapas.append(Etapa(chave, nome, "pendente"))
    return etapas


def etapa_atual(etapas: list[Etapa]) -> Etapa | None:
    return next((e for e in etapas if e.situacao == "atual"), None)
