"""Importação de extratos (§3.4): lê o arquivo (app/leitores), liga à conta bancária da empresa,
grava os movimentos sem duplicar e confere o saldo (inicial + entradas − saídas = final)."""

import calendar
import hashlib
from collections import Counter
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.leitores import ExtratoLido, ler_extrato
from app.modelos import (
    ContaBancaria,
    ContaChave,
    Empresa,
    Extrato,
    Importacao,
    MovimentoExtrato,
    Usuario,
)
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.contas_chave import identificar_banco, ligar_conta_bancaria, normalizar, referencia_bancaria
from app.servicos.plano import Aviso, ErroLeitura

ZERO = Decimal("0")


def _conta_bancaria(
    sessao: Session, empresa: Empresa, lido: ExtratoLido, usuario: Usuario | None
) -> tuple[ContaBancaria, str | None]:
    """A conta do extrato na empresa (criada no primeiro extrato) e a conta contábil dela (conta-chave)."""
    banco = identificar_banco(lido.banco)
    if banco is None:
        raise ErroLeitura(f"Não reconheci o banco “{lido.banco}” do extrato.")
    codigo, _, nome = banco
    de_outra = sessao.scalar(
        select(ContaBancaria).where(
            ContaBancaria.banco_codigo == codigo,
            ContaBancaria.agencia == lido.agencia,
            ContaBancaria.numero == lido.numero,
            ContaBancaria.tipo == lido.tipo,
            ContaBancaria.empresa_id != empresa.id,
        )
    )
    if de_outra is not None:
        dona = sessao.get(Empresa, de_outra.empresa_id)
        raise ErroLeitura(
            f"Este extrato é da conta {de_outra.rotulo}, que é da empresa {dona.nome} "
            f"(código {dona.codigo_dominio}). Confira se escolheu a empresa certa."
        )
    conta = sessao.scalar(
        select(ContaBancaria).where(
            ContaBancaria.empresa_id == empresa.id,
            ContaBancaria.banco_codigo == codigo,
            ContaBancaria.numero == lido.numero,
            ContaBancaria.tipo == lido.tipo,
        )
    )
    if conta is None:
        conta = ContaBancaria(
            empresa_id=empresa.id,
            banco_codigo=codigo,
            banco_nome=nome,
            agencia=lido.agencia,
            numero=lido.numero,
            tipo=lido.tipo,
            titular=lido.titular[:200] or None,
        )
        sessao.add(conta)
        sessao.flush()
    aviso_ia = None
    if conta.conta_chave is None or conta.conta_chave.conta_id is None:
        # a conta-chave pode já existir (achada pelo histórico: “BB conta 72637-0” → 8)
        chave = sessao.scalar(
            select(ContaChave).where(
                ContaChave.empresa_id == empresa.id,
                ContaChave.tipo == lido.tipo,
                ContaChave.referencia == referencia_bancaria(banco, lido.numero),
            )
        )
        if chave is None or chave.conta_id is None:
            chave, aviso_ia = ligar_conta_bancaria(sessao, empresa, nome, lido.agencia, lido.numero, lido.tipo, usuario)
        conta.conta_chave = chave
    return conta, aviso_ia


def reais_br(valor: Decimal) -> str:
    """Decimal('227494.23') → '227.494,23'."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def conferir_saldo(lido: ExtratoLido, entradas: Decimal, saidas: Decimal) -> tuple[str, Decimal | None]:
    """CONFERE, DIFERENCA (com o valor, quando dá para calcular) ou SEM_SALDO.
    - Saldo com os centavos cortados na impressão (e sem o sinal): confere se bater dentro de R$ 1,00.
    - Saldo anterior cortado no meio (“227.4”): o anterior é calculado pelo final e confere se começar
      com os dígitos que dá para ler (“227.494,23”)."""
    movimento = entradas - saidas
    if lido.saldo_inicial is None and lido.saldo_final is not None and lido.saldo_inicial_visivel:
        calculado = reais_br(abs(lido.saldo_final - movimento))
        confere = calculado.startswith(lido.saldo_inicial_visivel.lstrip("-"))
        return ("CONFERE", ZERO) if confere else ("DIFERENCA", None)
    if lido.saldo_inicial is None or lido.saldo_final is None:
        return "SEM_SALDO", None
    if not lido.saldo_cortado:
        diferenca = lido.saldo_final - (lido.saldo_inicial + movimento)
        return ("CONFERE", ZERO) if diferenca == 0 else ("DIFERENCA", diferenca)
    opcoes = [
        final - (inicial + movimento)
        for inicial in {lido.saldo_inicial, -lido.saldo_inicial}
        for final in {lido.saldo_final, -lido.saldo_final}
    ]
    menor = min(opcoes, key=abs)
    return ("CONFERE", ZERO) if abs(menor) < 1 else ("DIFERENCA", menor)


def _marca(conta: ContaBancaria, base: str, vez: int) -> str:
    return hashlib.sha256(f"{conta.id}|{base}#{vez}".encode()).hexdigest()


def importar_extrato(
    sessao: Session, empresa: Empresa, nome_arquivo: str, conteudo: bytes, usuario: Usuario | None
) -> Extrato:
    lido = ler_extrato(nome_arquivo, conteudo)
    conta, aviso_ia = _conta_bancaria(sessao, empresa, lido, usuario)
    arquivo = guardar_arquivo(sessao, empresa, "EXTRATO", nome_arquivo, conteudo, usuario)
    importacao = Importacao(
        empresa_id=empresa.id, tipo="EXTRATO", arquivo_id=arquivo.id, usuario_id=usuario.id if usuario else None
    )
    sessao.add(importacao)
    sessao.flush()

    entradas = sum((m.valor for m in lido.movimentos if m.sentido == "ENTRADA"), ZERO)
    saidas = sum((m.valor for m in lido.movimentos if m.sentido == "SAIDA"), ZERO)
    conferencia, diferenca = conferir_saldo(lido, entradas, saidas)
    if lido.saldo_inicial is None and lido.saldo_final is not None and lido.saldo_inicial_visivel:
        lido.saldo_inicial = lido.saldo_final - (entradas - saidas)  # o anterior saiu cortado no PDF
        lido.saldo_cortado = True
    datas = [m.data for m in lido.movimentos]
    extrato = Extrato(
        empresa_id=empresa.id,
        conta_bancaria_id=conta.id,
        importacao_id=importacao.id,
        leitor=lido.leitor[:60],
        inicio=lido.inicio or min(datas),
        fim=lido.fim or max(datas),
        saldo_inicial=lido.saldo_inicial,
        saldo_final=lido.saldo_final,
        saldo_cortado=lido.saldo_cortado,
        entradas=entradas,
        saidas=saidas,
        conferencia=conferencia,
        diferenca=diferenca,
    )
    sessao.add(extrato)
    sessao.flush()

    # anti-duplicidade: o mesmo movimento (mesma conta, dia, valor, histórico e documento) tem a mesma marca;
    # dois movimentos iguais no mesmo dia são o 1º e o 2º
    existentes = set(
        sessao.scalars(select(MovimentoExtrato.hash).where(MovimentoExtrato.conta_bancaria_id == conta.id))
    )
    vezes: Counter[str] = Counter()
    novos, repetidos = [], 0
    for ordem, movimento in enumerate(lido.movimentos, start=1):
        base = (
            f"{movimento.data.isoformat()}|{movimento.sentido}|{movimento.valor}|{normalizar(movimento.historico)}"
            f"|{normalizar(movimento.complemento)}|{movimento.documento}"
        )
        vezes[base] += 1
        marca = _marca(conta, base, vezes[base])
        if marca in existentes:
            repetidos += 1
            continue
        existentes.add(marca)
        novos.append(
            MovimentoExtrato(
                empresa_id=empresa.id,
                conta_bancaria_id=conta.id,
                extrato_id=extrato.id,
                ordem=ordem,
                data=movimento.data,
                valor=movimento.valor,
                sentido=movimento.sentido,
                historico=movimento.historico,
                complemento=movimento.complemento or None,
                documento=movimento.documento or None,
                codigo_banco=movimento.codigo or None,
                hash=marca,
            )
        )
    sessao.add_all(novos)

    avisos = list(lido.avisos)
    if conferencia == "DIFERENCA":
        avisos.insert(
            0,
            Aviso(
                (
                    f"O saldo não confere: saldo inicial + entradas − saídas difere do saldo final em "
                    f"R$ {reais_br(diferenca)}. "
                    if diferenca is not None
                    else "O saldo não confere: o saldo anterior calculado não bate com o que aparece no PDF. "
                )
                + "Pode faltar uma página ou uma linha do extrato — confira o arquivo."
            ),
        )
    if conta.conta_chave is None or conta.conta_chave.conta_id is None:
        avisos.insert(
            0,
            Aviso(
                f"Não encontrei no plano a conta contábil da {conta.rotulo}. Escolha na aba Plano de Contas "
                "(contas-chave) ou crie a conta no Domínio e reimporte o plano."
                + (f" ({aviso_ia})" if aviso_ia else "")
            ),
        )
    importacao.resumo = {
        "formato": lido.leitor,
        "conta": conta.rotulo,
        "movimentos": len(lido.movimentos),
        "novos": len(novos),
        "repetidos": repetidos,
        "de": extrato.inicio.isoformat(),
        "ate": extrato.fim.isoformat(),
        "conferencia": conferencia,
    }
    importacao.avisos = [asdict(aviso) for aviso in avisos]
    registrar_evento(
        sessao,
        "IMPORTAR_EXTRATO",
        detalhe=f"{empresa.nome}: {conta.rotulo}, {extrato.inicio:%d/%m/%Y} a {extrato.fim:%d/%m/%Y} — "
        f"{len(novos)} movimento(s) novo(s), {repetidos} repetido(s); saldo: {conferencia}",
    )
    sessao.flush()
    return extrato


# ---------------------------------------------------------------- consultas da tela


def limites_do_mes(competencia: date) -> tuple[date, date]:
    return competencia, date(
        competencia.year, competencia.month, calendar.monthrange(competencia.year, competencia.month)[1]
    )


def contas_bancarias(sessao: Session, empresa: Empresa) -> list[ContaBancaria]:
    return list(
        sessao.scalars(
            select(ContaBancaria)
            .where(ContaBancaria.empresa_id == empresa.id)
            .order_by(ContaBancaria.banco_nome, ContaBancaria.numero, ContaBancaria.tipo)
        )
    )


def extratos_do_mes(sessao: Session, empresa: Empresa, competencia: date) -> list[Extrato]:
    inicio, fim = limites_do_mes(competencia)
    return list(
        sessao.scalars(
            select(Extrato)
            .where(Extrato.empresa_id == empresa.id, Extrato.inicio <= fim, Extrato.fim >= inicio)
            .order_by(Extrato.conta_bancaria_id, Extrato.inicio, Extrato.id)
        )
    )


def movimentos_do_mes(sessao: Session, empresa: Empresa, competencia: date) -> list[MovimentoExtrato]:
    inicio, fim = limites_do_mes(competencia)
    return list(
        sessao.scalars(
            select(MovimentoExtrato)
            .where(MovimentoExtrato.empresa_id == empresa.id, MovimentoExtrato.data.between(inicio, fim))
            .order_by(
                MovimentoExtrato.conta_bancaria_id,
                MovimentoExtrato.data,
                MovimentoExtrato.extrato_id,
                MovimentoExtrato.ordem,
            )
        )
    )


def contar_movimentos_do_mes(sessao: Session, empresa: Empresa, competencia: date) -> int:
    inicio, fim = limites_do_mes(competencia)
    return (
        sessao.scalar(
            select(func.count())
            .select_from(MovimentoExtrato)
            .where(MovimentoExtrato.empresa_id == empresa.id, MovimentoExtrato.data.between(inicio, fim))
        )
        or 0
    )
