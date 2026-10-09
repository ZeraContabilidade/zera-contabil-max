"""Importação de extratos (§3.4): lê o arquivo (app/leitores), liga à conta bancária da empresa,
grava os movimentos sem duplicar e confere o saldo (inicial + entradas − saídas = final)."""

import hashlib
import re
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.leitores import ExtratoLido, NaoReconhecido, ler_extrato
from app.leitores.planilha import parece_planilha
from app.leitores.universal_ia import ler_pdf_com_ia
from app.modelos import (
    ArquivoOriginal,
    ContaBancaria,
    ContaChave,
    Empresa,
    Extrato,
    Importacao,
    MovimentoExtrato,
    Usuario,
)
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.classificacao import classificar
from app.servicos.competencia import Periodo, como_periodo
from app.servicos.contas_chave import identificar_banco, ligar_conta_bancaria, referencia_bancaria
from app.servicos.planilha_extrato import ler_planilha_extrato
from app.servicos.plano import Aviso, ErroLeitura

ZERO = Decimal("0")


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def mesma_conta(conta: ContaBancaria, agencia: str, numero: str) -> bool:
    """O mesmo número escrito de jeitos diferentes: “72637-0” (PDF) = “726370” = “0000726370” (OFX).
    A agência só desempata quando os dois lados a têm (muitos OFX vêm sem): “2180-6” = “2180”."""
    if _so_digitos(conta.numero).lstrip("0") != _so_digitos(numero).lstrip("0"):
        return False
    a, b = _so_digitos(conta.agencia)[:4], _so_digitos(agencia)[:4]
    return not a or not b or a.lstrip("0") == b.lstrip("0")


def _conta_bancaria(
    sessao: Session, empresa: Empresa, lido: ExtratoLido, usuario: Usuario | None
) -> tuple[ContaBancaria, str | None]:
    """A conta do extrato na empresa (criada no primeiro extrato) e a conta contábil dela (conta-chave)."""
    banco = identificar_banco(lido.banco)
    if banco is None:
        raise ErroLeitura(f"Não reconheci o banco “{lido.banco}” do extrato.")
    codigo, _, nome = banco
    mesmo_banco = sessao.scalars(
        select(ContaBancaria).where(ContaBancaria.banco_codigo == codigo, ContaBancaria.tipo == lido.tipo)
    ).all()
    iguais = [c for c in mesmo_banco if mesma_conta(c, lido.agencia, lido.numero)]
    de_outra = next((c for c in iguais if c.empresa_id != empresa.id), None)
    if de_outra is not None:
        dona = sessao.get(Empresa, de_outra.empresa_id)
        raise ErroLeitura(
            f"Este extrato é da conta {de_outra.rotulo}, que é da empresa {dona.nome} "
            f"(código {dona.rotulo_codigo}). Confira se escolheu a empresa certa."
        )
    conta = next((c for c in iguais if c.empresa_id == empresa.id), None)
    if conta is not None and not conta.agencia and lido.agencia:
        conta.agencia = lido.agencia  # o OFX às vezes vem sem agência; o PDF completa
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
    sessao: Session,
    empresa: Empresa,
    nome_arquivo: str,
    conteudo: bytes,
    usuario: Usuario | None,
    conta_escolhida: ContaBancaria | dict[str, str] | None = None,
    arquivo: ArquivoOriginal | None = None,
) -> Extrato:
    """`conta_escolhida` e `arquivo`: vindos da tela de confirmação de planilha (o arquivo já estava guardado)."""
    try:
        lido = ler_extrato(nome_arquivo, conteudo)
    except NaoReconhecido:
        if conteudo.lstrip()[:5] == b"%PDF-":
            lido = ler_pdf_com_ia(sessao, empresa, usuario, nome_arquivo, conteudo)  # banco sem leitor próprio
        elif parece_planilha(nome_arquivo, conteudo):
            lido = ler_planilha_extrato(sessao, empresa, usuario, nome_arquivo, conteudo, conta_escolhida)
        else:
            raise
    conta, aviso_ia = _conta_bancaria(sessao, empresa, lido, usuario)
    if lido.assinatura_planilha:
        conta.assinatura_planilha = lido.assinatura_planilha  # a próxima planilha igual vai direto para esta conta
    arquivo = arquivo or guardar_arquivo(sessao, empresa, "EXTRATO", nome_arquivo, conteudo, usuario)
    importacao = Importacao(
        empresa_id=empresa.id, tipo="EXTRATO", arquivo_id=arquivo.id, usuario_id=usuario.id if usuario else None
    )
    sessao.add(importacao)
    sessao.flush()

    entradas = sum((m.valor for m in lido.movimentos if m.sentido == "ENTRADA"), ZERO)
    saidas = sum((m.valor for m in lido.movimentos if m.sentido == "SAIDA"), ZERO)
    avisos = list(lido.avisos)
    if lido.saldo_inicial is None and not lido.saldo_inicial_visivel and lido.inicio:
        # o OFX não traz saldo inicial: vale o saldo final do extrato anterior desta conta, se ele acabou na véspera
        anterior = sessao.scalar(
            select(Extrato)
            .where(
                Extrato.conta_bancaria_id == conta.id,
                Extrato.fim == lido.inicio - timedelta(days=1),
                Extrato.saldo_final.is_not(None),
            )
            .order_by(Extrato.id.desc())
        )
        if anterior is not None:
            lido.saldo_inicial = anterior.saldo_final
            lido.saldo_cortado = lido.saldo_cortado or anterior.saldo_cortado
        elif lido.saldo_final is not None:
            avisos.append(
                Aviso(
                    "O arquivo não traz o saldo inicial: a conferência do saldo fica para quando o extrato do "
                    "mês anterior desta conta estiver no sistema."
                )
            )
    conferencia, diferenca = conferir_saldo(lido, entradas, saidas)
    if lido.exige_conferencia and conferencia != "CONFERE":
        situacao = "não há saldo inicial e final para conferir" if conferencia == "SEM_SALDO" else "o saldo não bate"
        raise ErroLeitura(
            f"A IA leu o extrato “{nome_arquivo}”, mas {situacao}. Para não arriscar lançamento errado, o arquivo "
            "não foi importado: mande o OFX ou o Excel do banco."
        )
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

    # anti-duplicidade: mesma conta, dia, sentido e valor = o mesmo movimento (o 1º, o 2º... do dia).
    # O texto fica de fora de propósito: o PDF e o OFX do mesmo mês escrevem o histórico de jeitos diferentes.
    existentes = set(
        sessao.scalars(select(MovimentoExtrato.hash).where(MovimentoExtrato.conta_bancaria_id == conta.id))
    )
    vezes: Counter[str] = Counter()
    novos, repetidos = [], 0
    for ordem, movimento in enumerate(lido.movimentos, start=1):
        base = f"{movimento.data.isoformat()}|{movimento.sentido}|{movimento.valor}"
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
                f"Não encontrei no plano a conta contábil da {conta.rotulo}: nos lançamentos ela fica em branco "
                "(complete no Domínio). Se a conta existir, escolha na aba Plano de Contas (contas-chave) ou crie "
                "no Domínio e reimporte o plano." + (f" ({aviso_ia})" if aviso_ia else "")
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
    # classifica o período inteiro (todas as contas): a transferência acha o par no extrato da outra conta
    resultado = classificar(sessao, empresa, extrato.inicio, extrato.fim)
    importacao.resumo = {**importacao.resumo, "classificacao": resultado.resumo()}
    return extrato


# ---------------------------------------------------------------- consultas da tela


def limites_do_mes(competencia: date | Periodo) -> tuple[date, date]:
    """1º e último dia do mês — ou do período inteiro (de um mês até outro)."""
    return como_periodo(competencia).limites


def contas_bancarias(sessao: Session, empresa: Empresa) -> list[ContaBancaria]:
    return list(
        sessao.scalars(
            select(ContaBancaria)
            .where(ContaBancaria.empresa_id == empresa.id)
            .order_by(ContaBancaria.banco_nome, ContaBancaria.numero, ContaBancaria.tipo)
        )
    )


def extratos_do_mes(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> list[Extrato]:
    inicio, fim = limites_do_mes(competencia)
    return list(
        sessao.scalars(
            select(Extrato)
            .where(Extrato.empresa_id == empresa.id, Extrato.inicio <= fim, Extrato.fim >= inicio)
            .order_by(Extrato.conta_bancaria_id, Extrato.inicio, Extrato.id)
        )
    )


def movimentos_do_mes(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> list[MovimentoExtrato]:
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


def contar_movimentos_do_mes(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> int:
    inicio, fim = limites_do_mes(competencia)
    return (
        sessao.scalar(
            select(func.count())
            .select_from(MovimentoExtrato)
            .where(MovimentoExtrato.empresa_id == empresa.id, MovimentoExtrato.data.between(inicio, fim))
        )
        or 0
    )
