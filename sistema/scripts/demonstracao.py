"""Dados de DEMONSTRAÇÃO (todos fictícios) para o servidor de teste: a “Creche Exemplo” ganha plano de contas,
histórico (o lanctos.txt anonimizado dos testes) e extratos OFX de agosto e setembro de 2026 — assim as telas de
Extratos, Revisão, Exportar e o Painel aparecem cheias, como no uso real. Só roda no banco `_teste`."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PASTA_SISTEMA
from app.modelos import ContaChave, ContaContabil, Empresa
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.competencia import Periodo
from app.servicos.extratos import importar_extrato

HISTORICO = PASTA_SISTEMA / "tests" / "dados" / "lanctos_exemplo.txt"

# (dia, valor, histórico do banco, favorecido) — os mesmos nomes do histórico de exemplo, alguns cortados como no banco
MOVIMENTOS = [
    (1, "12500.00", "Transferência recebida", "PREFEITURA MUNICIPAL EXEMPLO"),
    (3, "-98.10", "Pagamento de Boleto", "COMPANHIA DE AGUA EXEMPL"),
    (5, "-910.00", "Pagamento de Boleto", "INTERMEDIADORA DE PAGAMENTO"),
    (6, "-2861.25", "Transferência enviada", "MARIA SOUZA"),
    (6, "-1490.00", "Transferência enviada", "JOANA SILVA"),
    (7, "-12.50", "Tarifa Pacote de Serviços", ""),
    (10, "-346.50", "Pix - Enviado", "11.222.333 SINDICATO EXE"),
    (12, "-158.20", "Pix - Enviado", "TRANSPORTES EXEMPLO S/A"),
    (15, "-623.40", "Pagamento de Boleto", "MERCADO MISTO LTDA"),
    (18, "-77.00", "Pix - Enviado", "FULANO DESCONHECIDO"),
    (20, "-45.00", "Pix - Enviado", "MERCEARIA ZETA"),
    (22, "-480.00", "Pagamento de Boleto", "PAPELARIA CENTRAL"),
    (27, "-52.00", "Pix - Enviado", "MERCEARIA ZETA"),
]


def montar_ofx(mes: date, saldo_final: Decimal) -> bytes:
    """Um OFX no jeito do Banco do Brasil (SGML, Windows-1252, MEMO “HISTÓRICO - dd/mm hh:mm FAVORECIDO”)."""
    fim = Periodo.do_mes(mes).ultimo_dia
    linhas = [
        "OFXHEADER:100", "DATA:OFXSGML", "VERSION:102", "SECURITY:NONE", "ENCODING:USASCII", "CHARSET:1252",
        "COMPRESSION:NONE", "OLDFILEUID:NONE", "NEWFILEUID:NONE", "",
        "<OFX><BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS><CURDEF>BRL",
        "<BANKACCTFROM><BANKID>001<BRANCHID>1234-5<ACCTID>12345-6<ACCTTYPE>CHECKING</BANKACCTFROM>",
        f"<BANKTRANLIST><DTSTART>{mes:%Y%m%d}<DTEND>{fim:%Y%m%d}",
    ]  # fmt: skip
    for numero, (dia, valor, historico, favorecido) in enumerate(MOVIMENTOS, 1):
        quando = date(mes.year, mes.month, dia)
        memo = f"{historico} - {quando:%d/%m} 10:{numero:02d} {favorecido}" if favorecido else historico
        tipo = "DEBIT" if valor.startswith("-") else "CREDIT"
        linhas += [
            f"<STMTTRN><TRNTYPE>{tipo}<DTPOSTED>{quando:%Y%m%d}120000[-3:BRT]<TRNAMT>{valor}",
            f"<FITID>{quando:%Y%m%d}{numero:03d}<CHECKNUM>{numero:06d}<MEMO>{memo}</STMTTRN>",
        ]
    linhas.append(f"</BANKTRANLIST><LEDGERBAL><BALAMT>{saldo_final}<DTASOF>{fim:%Y%m%d}</LEDGERBAL>")
    linhas.append("</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>")
    return "\r\n".join(linhas).encode("cp1252")


def preparar_demonstracao(sessao: Session, empresa: Empresa) -> None:
    from tests.planos import criar_plano  # o mesmo plano fictício dos testes

    criar_plano(sessao, empresa)
    historico = HISTORICO.read_bytes().replace(b";230;", f";{empresa.codigo_no_lanctos};".encode())
    importar_historico(sessao, empresa, "lanctos.txt", historico, None)
    aprender(sessao, empresa)
    tarifa = sessao.scalar(
        select(ContaContabil).where(ContaContabil.empresa_id == empresa.id, ContaContabil.reduzido == 535)
    )
    if tarifa:
        sessao.add(ContaChave(empresa_id=empresa.id, tipo="TARIFA", referencia="", conta_id=tarifa.id, origem="REGRA"))
    sessao.commit()
    saldo = Decimal("0")
    movimento_do_mes = sum(Decimal(valor) for _, valor, _, _ in MOVIMENTOS)
    for mes in (date(2026, 8, 1), date(2026, 9, 1)):
        saldo += movimento_do_mes
        importar_extrato(sessao, empresa, f"Extrato{mes:%Y%m}.ofx", montar_ofx(mes, saldo), None)
        sessao.commit()
