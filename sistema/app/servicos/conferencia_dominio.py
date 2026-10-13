"""Conferir com o Domínio: depois de importar o lanctos.txt, o escritório digita o saldo de cada conta banco no
Domínio no fim do mês e o sistema compara com o saldo final do extrato (sugestão de 13/10). Digitado — e não lido de
um relatório — porque ainda não há um exemplo do Razão do Domínio (não inventar formato, §11)."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import ConferenciaDominio, ContaBancaria, Empresa, Extrato, Usuario
from app.servicos.competencia import Periodo, como_periodo
from app.servicos.extratos import extratos_do_mes, reais_br

TOLERANCIA = Decimal("0.01")
TOLERANCIA_CORTADO = Decimal("1.00")  # PDF que cortou os centavos do saldo
_NUMERO = re.compile(r"[-+]?[\d.,]+")


def ler_saldo(texto: str | None) -> Decimal | None | bool:
    """Como o Domínio mostra: '12.345,67', '12.345,67D' (devedor = positivo), '1.000,00C' (credor = negativo),
    '-1.000,00' ou '1234.56'. Vazio → None; ilegível → False."""
    bruto = (texto or "").upper().replace("R$", "").replace(" ", "")
    if not bruto:
        return None
    credor = bruto.endswith("C")
    bruto = bruto.rstrip("CD")
    if not _NUMERO.fullmatch(bruto):
        return False
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(bruto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return False
    return -valor if credor else valor


@dataclass
class LinhaConferencia:
    conta: ContaBancaria
    mes: date
    saldo_extrato: Decimal | None
    sem_saldo: str  # por que não há saldo do extrato no fim do mês (vazio = há)
    cortado: bool
    informado: ConferenciaDominio | None

    @property
    def chave(self) -> str:
        return f"{self.conta.id}-{self.mes:%Y-%m}"

    @property
    def diferenca(self) -> Decimal | None:
        if self.informado is None or self.saldo_extrato is None:
            return None
        return self.informado.saldo_dominio - self.saldo_extrato

    @property
    def texto_diferenca(self) -> str:
        """“o Domínio tem R$ 12,30 a mais que o extrato” (vazio quando não há o que comparar)."""
        if self.diferenca is None:
            return ""
        lado = "a mais" if self.diferenca > 0 else "a menos"
        return f"o Domínio tem R$ {reais_br(abs(self.diferenca))} {lado} que o extrato"

    @property
    def situacao(self) -> str:
        """BATE, DIFERENCA, FALTA (ainda não digitado) ou SEM_EXTRATO (o extrato não dá o saldo do fim do mês)."""
        if self.saldo_extrato is None:
            return "SEM_EXTRATO"
        if self.informado is None:
            return "FALTA"
        limite = TOLERANCIA_CORTADO if self.cortado else TOLERANCIA
        return "BATE" if abs(self.diferenca) <= limite else "DIFERENCA"


def _saldo_do_fim_do_mes(extratos: list[Extrato], ultimo_dia: date) -> tuple[Decimal | None, str, bool]:
    final = max(extratos, key=lambda e: (e.fim, e.id))
    if final.fim < ultimo_dia:
        return None, f"o extrato vai só até {final.fim:%d/%m}", False
    if final.fim > ultimo_dia:
        return None, f"o extrato vai até {final.fim:%d/%m} (o saldo não é o do fim do mês)", False
    if final.saldo_final is None:
        return None, "o extrato não traz o saldo final", False
    return final.saldo_final, "", final.saldo_cortado


def linhas_conferencia(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> list[LinhaConferencia]:
    linhas = []
    for mes in como_periodo(competencia).meses:
        ultimo_dia = Periodo.do_mes(mes).ultimo_dia
        extratos = extratos_do_mes(sessao, empresa, mes)
        informados = {
            c.conta_bancaria_id: c
            for c in sessao.scalars(
                select(ConferenciaDominio).where(
                    ConferenciaDominio.empresa_id == empresa.id, ConferenciaDominio.mes == mes
                )
            )
        }
        contas = {e.conta_bancaria_id: e.conta_bancaria for e in extratos}
        for conta in sorted(contas.values(), key=lambda c: c.rotulo):
            da_conta = [e for e in extratos if e.conta_bancaria_id == conta.id]
            saldo, motivo, cortado = _saldo_do_fim_do_mes(da_conta, ultimo_dia)
            linhas.append(LinhaConferencia(conta, mes, saldo, motivo, cortado, informados.get(conta.id)))
    return linhas


def informar_saldos(
    sessao: Session,
    empresa: Empresa,
    competencia: date | Periodo,
    digitados: dict[str, str],
    usuario: Usuario | None,
) -> tuple[list[LinhaConferencia], list[str]]:
    """`digitados` = {"<conta>-<AAAA-MM>": "12.345,67D"}. Grava o que veio preenchido (vazio apaga o que havia).
    Devolve (linhas gravadas, erros em português)."""
    gravadas, erros = [], []
    for linha in linhas_conferencia(sessao, empresa, competencia):
        if linha.chave not in digitados:
            continue
        valor = ler_saldo(digitados[linha.chave])
        if valor is False:
            erros.append(
                f"{linha.conta.rotulo}: “{digitados[linha.chave]}” não é um valor (ex.: 12.345,67 ou 12.345,67D)."
            )
            continue
        if valor is None:
            if linha.informado is not None:
                sessao.delete(linha.informado)
            continue
        if linha.informado is None:
            linha.informado = ConferenciaDominio(empresa_id=empresa.id, conta_bancaria_id=linha.conta.id, mes=linha.mes)
            sessao.add(linha.informado)
        linha.informado.saldo_dominio = valor
        linha.informado.informado_por_id = usuario.id if usuario else None
        gravadas.append(linha)
    sessao.flush()
    return gravadas, erros
