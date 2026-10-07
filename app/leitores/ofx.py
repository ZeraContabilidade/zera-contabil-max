"""OFX de qualquer banco (§3.4, regra 1). Leitor próprio e tolerante: os OFX dos bancos brasileiros
costumam vir em SGML (OFX 1.x, sem fechar as tags), em Windows-1252 e às vezes com vírgula decimal —
coisas que leitores rígidos recusam. Também lê OFX 2.x (XML).

Campos usados: BANKID (código do banco), BRANCHID (agência), ACCTID (conta), ACCTTYPE (tipo),
DTSTART/DTEND (período), STMTTRN (movimentos: DTPOSTED, TRNAMT com sinal, MEMO/NAME, CHECKNUM/REFNUM)
e LEDGERBAL (saldo final). O OFX não traz saldo inicial.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.leitores import ArquivoExtrato, ExtratoLido, MovimentoLido
from app.servicos.plano import Aviso, ErroLeitura

TIPOS = {"CHECKING": "BANCO", "SAVINGS": "POUPANCA", "MONEYMRKT": "APLICACAO", "CD": "APLICACAO"}


def _campo(bloco: str, tag: str) -> str:
    """Valor de <TAG>valor (SGML, sem fechar) ou <TAG>valor</TAG> (XML)."""
    achado = re.search(rf"<{tag}>\s*([^<\r\n]*)", bloco, re.IGNORECASE)
    return " ".join(achado.group(1).split()) if achado else ""


def _blocos(texto: str, tag: str) -> list[str]:
    """Pedaços do arquivo que começam em <TAG> e vão até </TAG> ou até o próximo <TAG>."""
    partes = re.split(rf"<{tag}>", texto, flags=re.IGNORECASE)[1:]
    return [re.split(rf"</{tag}>", parte, maxsplit=1, flags=re.IGNORECASE)[0] for parte in partes]


def _data(texto: str) -> date | None:
    try:
        return datetime.strptime(texto[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _valor(texto: str) -> Decimal | None:
    """'-330.36', '-330,36' ou '-1.234,56' → Decimal com sinal."""
    texto = texto.replace(" ", "").replace("+", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


_HORA_NO_COMECO = re.compile(r"^\d{2}/\d{2}\s+\d{2}:\d{2}\s+")


def _separar_memo(memo: str) -> tuple[str, str]:
    """'TRANSFERÊNCIA RECEBIDA - 04/12 12:19 APAE A DE P' → ('TRANSFERÊNCIA RECEBIDA', 'APAE A DE P');
    'PIX - ENVIADO - 03/08 09:43 QUATAI' → ('PIX - ENVIADO', 'QUATAI') — o favorecido vem depois do último “ - ”."""
    if " - " not in memo:
        return memo, ""
    historico, complemento = memo.rsplit(" - ", 1)
    return historico.strip(), _HORA_NO_COMECO.sub("", complemento).strip()


def _agencia_pelo_nome(nome_arquivo: str, numero: str) -> str:
    """O OFX do BB não traz a agência, mas o nome do arquivo sim: 'Extrato21806112267.ofx' = agência 2180-6 +
    conta 11226-7. Só vale quando os números do nome terminam com os da conta."""
    digitos = re.sub(r"\D", "", re.sub(r"\(\d+\)", "", nome_arquivo))
    conta = re.sub(r"\D", "", numero)
    if not conta or not digitos.endswith(conta) or len(digitos) - len(conta) not in (4, 5):
        return ""
    agencia = digitos[: -len(conta)]
    return f"{agencia[:4]}-{agencia[4]}" if len(agencia) == 5 else agencia


class LeitorOFX:
    nome = "OFX"

    def reconhece(self, arquivo: ArquivoExtrato) -> bool:
        if arquivo.eh_pdf:
            return False
        inicio = arquivo.texto[:2000].upper()
        return "OFXHEADER" in inicio or "<OFX>" in arquivo.texto.upper()

    def ler(self, arquivo: ArquivoExtrato) -> ExtratoLido:
        texto = arquivo.texto
        if not _blocos(texto, "STMTRS"):
            if _blocos(texto, "CCSTMTRS"):
                raise ErroLeitura("Este OFX é de cartão de crédito. Por enquanto o sistema lê só contas bancárias.")
            if _blocos(texto, "STMTTRNRS"):
                raise ErroLeitura(
                    "O OFX veio vazio do banco: não tem extrato dentro (exportação incompleta ou período sem "
                    "dados). Baixe de novo no internet banking, escolhendo a conta e o mês."
                )
            raise ErroLeitura("O OFX não tem extrato de conta bancária (falta o bloco STMTRS).")
        extratos = _blocos(texto, "STMTRS")
        if len(extratos) > 1:
            raise ErroLeitura(
                f"Este OFX tem {len(extratos)} contas juntas. Exporte do banco um arquivo para cada conta."
            )
        bloco = extratos[0]
        conta = (_blocos(bloco, "BANKACCTFROM") or [bloco])[0]
        banco = _campo(conta, "BANKID") or _campo(texto, "ORG")
        lido = ExtratoLido(
            leitor=self.nome,
            banco=banco.lstrip("0").zfill(3) if banco.isdigit() else banco,
            agencia=_campo(conta, "BRANCHID"),
            numero=_campo(conta, "ACCTID"),
            tipo=TIPOS.get(_campo(conta, "ACCTTYPE").upper(), "BANCO"),
        )
        if not lido.numero:
            raise ErroLeitura("O OFX não traz o número da conta (ACCTID). Exporte o arquivo de novo pelo banco.")
        if not lido.agencia:
            lido.agencia = _agencia_pelo_nome(arquivo.nome, lido.numero)

        ignorados = []
        for transacao in _blocos(bloco, "STMTTRN"):
            dia, valor = _data(_campo(transacao, "DTPOSTED")), _valor(_campo(transacao, "TRNAMT"))
            memo, nome = _campo(transacao, "MEMO"), _campo(transacao, "NAME")
            if dia is None or not valor:
                ignorados.append(f"{_campo(transacao, 'DTPOSTED')[:8]} {memo or nome} {_campo(transacao, 'TRNAMT')}")
                continue
            historico, complemento = _separar_memo(memo or nome or _campo(transacao, "TRNTYPE").title())
            if memo and nome and nome.upper() not in memo.upper():
                complemento = nome
            lido.movimentos.append(
                MovimentoLido(
                    data=dia,
                    valor=abs(valor),
                    sentido="ENTRADA" if valor > 0 else "SAIDA",
                    historico=historico[:120],
                    complemento=complemento[:200],
                    documento=(_campo(transacao, "CHECKNUM") or _campo(transacao, "REFNUM"))[:60],
                )
            )

        lista = (_blocos(bloco, "BANKTRANLIST") or [bloco])[0]
        lido.inicio, lido.fim = _data(_campo(lista, "DTSTART")), _data(_campo(lista, "DTEND"))
        if lido.movimentos:
            lido.inicio = lido.inicio or min(m.data for m in lido.movimentos)
            lido.fim = lido.fim or max(m.data for m in lido.movimentos)
        if lido.inicio is None:
            raise ErroLeitura("O OFX não tem movimentos nem período. Confira se exportou o mês certo.")
        # o BB começa o período no dia do saldo anterior (26/11 num extrato de dezembro): vale o mês dos movimentos
        primeiro_dia = lido.fim.replace(day=1)
        if lido.inicio < primeiro_dia and all(m.data >= primeiro_dia for m in lido.movimentos):
            lido.inicio = primeiro_dia
        if saldo := _blocos(bloco, "LEDGERBAL"):
            quando = _data(_campo(saldo[0], "DTASOF"))
            if quando is None or quando <= lido.fim:
                lido.saldo_final = _valor(_campo(saldo[0], "BALAMT"))
            else:  # o BB manda o saldo do dia em que o arquivo foi baixado, não o do fim do período
                lido.avisos.append(
                    Aviso(
                        f"O saldo que veio no OFX é de {quando:%d/%m/%Y}, depois do fim do extrato "
                        f"({lido.fim:%d/%m/%Y}): não serve para conferir este período."
                    )
                )
        if ignorados:
            lido.avisos.append(
                Aviso(f"{len(ignorados)} movimento(s) sem data ou sem valor foram ignorados.", ignorados)
            )
        return lido
