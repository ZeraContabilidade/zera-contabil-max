"""Painel do Supervisor (§2, §8): todas as empresas × mês — onde cada uma parou, quanto saiu sozinho (a meta do
projeto: ≥ 85% no 1º mês, ≥ 95% depois), correções à mão, IA e quem exportou."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import ChamadaIA, Empresa, Exportacao, MovimentoExtrato, Sugestao
from app.servicos.extratos import limites_do_mes
from app.servicos.progresso import Etapa, etapa_atual, progresso_do_mes

ABA_DA_ETAPA = {
    "plano": "plano",
    "aprendizado": "aprendizado",
    "extrato": "extratos",
    "revisao": "revisao",
    "exportado": "exportar",
}


@dataclass
class NumerosMes:
    movimentos: int = 0
    sem_lancamento: int = 0
    aprovados: int = 0  # aprovados + exportados
    pendentes: int = 0
    automaticos: int = 0  # aprovados sem ninguém mexer nem conferir
    correcoes: int = 0  # conta escolhida à mão na Revisão
    pela_ia: int = 0  # aprovados com a conta que a IA deu
    exportados: int = 0

    @property
    def com_lancamento(self) -> int:
        return self.movimentos - self.sem_lancamento

    @property
    def automatico(self) -> int | None:
        """% classificado automaticamente (sem conferência humana) das linhas que geram lançamento."""
        return round(100 * self.automaticos / self.com_lancamento) if self.com_lancamento else None

    def somar(self, outro: "NumerosMes") -> None:
        for campo in self.__dataclass_fields__:
            setattr(self, campo, getattr(self, campo) + getattr(outro, campo))


def numeros_do_mes(sessao: Session, competencia: date) -> dict[int, NumerosMes]:
    inicio, fim = limites_do_mes(competencia)
    numeros: dict[int, NumerosMes] = defaultdict(NumerosMes)
    consulta = (
        select(
            Sugestao.empresa_id,
            Sugestao.status,
            Sugestao.origem,
            Sugestao.conferido_por_id.is_(None),
            func.count(),
        )
        .join(MovimentoExtrato, Sugestao.movimento_id == MovimentoExtrato.id)
        .where(MovimentoExtrato.data.between(inicio, fim))
        .group_by(Sugestao.empresa_id, Sugestao.status, Sugestao.origem, Sugestao.conferido_por_id.is_(None))
    )
    for empresa_id, status, origem, sem_conferencia, vezes in sessao.execute(consulta):
        n = numeros[empresa_id]
        n.movimentos += vezes
        if status == "IGNORADO":
            n.sem_lancamento += vezes
        elif status == "PENDENTE":
            n.pendentes += vezes
        else:  # APROVADO ou EXPORTADO
            n.aprovados += vezes
            n.exportados += vezes if status == "EXPORTADO" else 0
            n.automaticos += vezes if sem_conferencia and origem != "USUARIO" else 0
            n.pela_ia += vezes if origem == "IA" else 0
        n.correcoes += vezes if origem == "USUARIO" else 0
    return numeros


@dataclass
class LinhaPainel:
    empresa: Empresa
    etapas: list[Etapa]
    numeros: NumerosMes
    exportacao: Exportacao | None  # a última válida (não reaberta) do mês

    @property
    def atual(self) -> Etapa | None:
        return etapa_atual(self.etapas)

    @property
    def aba(self) -> str:
        return ABA_DA_ETAPA.get(self.atual.chave, "cadastro") if self.atual else "exportar"


@dataclass
class Painel:
    competencia: date
    linhas: list[LinhaPainel] = field(default_factory=list)
    total: NumerosMes = field(default_factory=NumerosMes)
    concluidas: int = 0


def painel(sessao: Session, competencia: date, responsavel_id: int | None = None, so_pendencia: bool = False) -> Painel:
    numeros = numeros_do_mes(sessao, competencia)
    exportacoes: dict[int, Exportacao] = {}
    for exportacao in sessao.scalars(
        select(Exportacao)
        .where(Exportacao.competencia == competencia, Exportacao.reaberta_em.is_(None))
        .order_by(Exportacao.criado_em)
    ):
        exportacoes[exportacao.empresa_id] = exportacao  # fica a mais recente
    consulta = select(Empresa).where(Empresa.ativa).order_by(func.coalesce(Empresa.nome_curto, Empresa.razao_social))
    if responsavel_id:
        consulta = consulta.where(Empresa.responsavel_id == responsavel_id)
    resultado = Painel(competencia)
    for empresa in sessao.scalars(consulta):
        linha = LinhaPainel(
            empresa, progresso_do_mes(sessao, empresa, competencia), numeros[empresa.id], exportacoes.get(empresa.id)
        )
        if linha.atual is None:  # mês concluído (tudo exportado)
            resultado.concluidas += 1
            if so_pendencia:
                continue
        resultado.linhas.append(linha)
        resultado.total.somar(linha.numeros)
    return resultado


@dataclass
class UsoIA:
    empresa: Empresa
    chamadas: int
    custo: Decimal
    linhas: int  # aprovadas com a conta que a IA deu (todos os meses)

    @property
    def custo_por_linha(self) -> Decimal | None:
        return self.custo / self.linhas if self.linhas else None


def uso_da_ia_por_empresa(sessao: Session) -> list[UsoIA]:
    """Desde o início: quanto a IA custou e quantas linhas ela resolveu em cada empresa."""
    gastos = {
        empresa_id: (chamadas, custo)
        for empresa_id, chamadas, custo in sessao.execute(
            select(ChamadaIA.empresa_id, func.count(), func.coalesce(func.sum(ChamadaIA.custo_usd), 0))
            .where(ChamadaIA.empresa_id.is_not(None))
            .group_by(ChamadaIA.empresa_id)
        )
    }
    resolvidas = dict(
        sessao.execute(
            select(Sugestao.empresa_id, func.count())
            .where(Sugestao.origem == "IA", Sugestao.status.in_(("APROVADO", "EXPORTADO")))
            .group_by(Sugestao.empresa_id)
        ).all()
    )
    usos = []
    for empresa in sessao.scalars(select(Empresa).where(Empresa.id.in_(set(gastos) | set(resolvidas)))):
        chamadas, custo = gastos.get(empresa.id, (0, Decimal("0")))
        usos.append(UsoIA(empresa, chamadas, Decimal(custo), resolvidas.get(empresa.id, 0)))
    return sorted(usos, key=lambda u: (-u.custo, u.empresa.nome))
