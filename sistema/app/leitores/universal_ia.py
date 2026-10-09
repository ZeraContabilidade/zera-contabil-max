"""Leitor universal com IA (§3.4, regra 4): PDF de banco que ainda não tem leitor próprio.

O texto de cada página vai para a IA (modelo forte), que devolve os movimentos em JSON; as páginas são
juntadas e a resposta é conferida (datas, valores, sentido). O extrato só entra se a conferência de
saldo bater (`exige_conferencia`): se não bater, o serviço recusa e pede o OFX ou o Excel do banco.
Uma página por chamada: a resposta fica pequena e rápida (o extrato inteiro poderia passar do tempo).
"""

import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber
from sqlalchemy.orm import Session

from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import IAIndisponivel, chamar_ia
from app.leitores import ExtratoLido, MovimentoLido
from app.modelos import Empresa, Usuario
from app.servicos.plano import Aviso, ErroLeitura

NOME = "Leitura pela IA (PDF)"
MAXIMO_DE_PAGINAS = 15

INSTRUCOES = """Você lê extratos bancários brasileiros para o sistema ZERA CONTÁBIL MAX. Recebe o TEXTO de UMA \
página de um extrato em PDF, extraído automaticamente: as colunas podem estar desalinhadas e uma descrição pode \
continuar na linha de baixo (o favorecido costuma vir na linha seguinte ao lançamento). Responda só o JSON pedido.

- e_extrato: false se a página não for de extrato de conta (comprovante, boleto, fatura de cartão, página em branco).
- banco, agencia, conta, titular: como aparecem no cabeçalho desta página; "" se ela não mostra.
- tipo: BANCO (conta corrente), POUPANCA ou APLICACAO.
- inicio e fim: período do extrato (AAAA-MM-DD) se a página mostrar; senão "".
- saldo_inicial: o saldo anterior/inicial do período, se aparecer nesta página; saldo_final: o saldo final do \
período, se aparecer. Negativo (com “-”) quando for devedor (D ou -). "" quando não aparecer.
- movimentos: cada lançamento da página, na ordem: data (AAAA-MM-DD), historico (o tipo do lançamento, ex.: PIX \
ENVIADO, PAGAMENTO DE BOLETO, TARIFA), complemento (favorecido ou pagador e o resto da informação, sem data e \
hora), documento ("" se não houver), valor (sempre positivo), sentido (ENTRADA = crédito, SAIDA = débito).
- NÃO inclua linhas de saldo (saldo anterior, saldo do dia, saldo final), totais, limites nem bloqueios.
- Todos os valores com ponto decimal e sem separador de milhar (ex.: 1234.56). Copie os números exatamente \
como estão: nunca invente, some ou arredonde."""

_TEXTO = {"type": "string"}
ESQUEMA = {
    "type": "object",
    "properties": {
        "e_extrato": {"type": "boolean"},
        "banco": _TEXTO,
        "agencia": _TEXTO,
        "conta": _TEXTO,
        "tipo": {"type": "string", "enum": ["BANCO", "POUPANCA", "APLICACAO"]},
        "titular": _TEXTO,
        "inicio": _TEXTO,
        "fim": _TEXTO,
        "saldo_inicial": _TEXTO,
        "saldo_final": _TEXTO,
        "movimentos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "data": _TEXTO,
                    "historico": _TEXTO,
                    "complemento": _TEXTO,
                    "documento": _TEXTO,
                    "valor": _TEXTO,
                    "sentido": {"type": "string", "enum": ["ENTRADA", "SAIDA"]},
                },
                "required": ["data", "historico", "complemento", "documento", "valor", "sentido"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "e_extrato", "banco", "agencia", "conta", "tipo", "titular",
        "inicio", "fim", "saldo_inicial", "saldo_final", "movimentos",
    ],
    "additionalProperties": False,
}  # fmt: skip


def paginas_do_pdf(conteudo: bytes) -> list[str]:
    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            return [pagina.extract_text() or "" for pagina in pdf.pages]
    except Exception as erro:
        raise ErroLeitura("Não consegui abrir o PDF. Baixe o extrato de novo no internet banking.") from erro


def _data(texto: str) -> date | None:
    try:
        return date.fromisoformat(str(texto).strip()[:10])
    except ValueError:
        return None


def _decimal(texto: str) -> Decimal | None:
    texto = str(texto or "").strip().replace(" ", "").replace("R$", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto).quantize(Decimal("0.01")) if texto else None
    except InvalidOperation:
        return None


def ler_pdf_com_ia(
    sessao: Session, empresa: Empresa, usuario: Usuario | None, nome: str, conteudo: bytes
) -> ExtratoLido:
    paginas = [texto for texto in paginas_do_pdf(conteudo) if texto.strip()]
    if not paginas:
        raise ErroLeitura(f"O PDF “{nome}” não tem texto. Baixe o extrato em PDF pelo internet banking ou em OFX.")
    if len(paginas) > MAXIMO_DE_PAGINAS:
        raise ErroLeitura(
            f"O PDF “{nome}” tem {len(paginas)} páginas: grande demais para ler com a IA. Mande o OFX do banco."
        )
    respostas = []
    for numero, texto in enumerate(paginas, start=1):
        pedido = PedidoIA(
            finalidade="leitura_pdf",
            instrucoes=INSTRUCOES,
            pergunta=f"Página {numero} de {len(paginas)} do arquivo “{nome}”:\n\n{texto}",
            esquema=ESQUEMA,
            forte=True,
            max_tokens=16000,
        )
        try:
            respostas.append(chamar_ia(sessao, pedido, empresa, usuario).dados)
        except IAIndisponivel as erro:
            raise ErroLeitura(
                f"Não reconheci o extrato “{nome}”: este banco ainda não tem leitor próprio e a leitura com IA "
                f"não está disponível ({erro}). Mande o OFX do banco."
            ) from erro
        except ErroIA as erro:
            raise ErroLeitura(f"A IA não conseguiu ler o extrato “{nome}” ({erro}). Mande o OFX do banco.") from erro
    return juntar_paginas(respostas)


def juntar_paginas(respostas: list[dict]) -> ExtratoLido:
    """Cabeçalho da primeira página que o mostra; saldo inicial da primeira, final da última; movimentos em ordem.
    Tudo conferido: o que não fizer sentido (data fora do período, valor inválido) fica de fora com aviso."""
    paginas = [r for r in respostas if r.get("e_extrato")]
    if not paginas:
        raise ErroLeitura("O arquivo não parece um extrato bancário (a IA não encontrou lançamentos de conta).")

    def primeiro(campo: str) -> str:
        return next((str(p.get(campo) or "").strip() for p in paginas if str(p.get(campo) or "").strip()), "")

    lido = ExtratoLido(
        leitor=NOME,
        banco=primeiro("banco"),
        agencia=primeiro("agencia"),
        numero=primeiro("conta"),
        tipo=primeiro("tipo") if primeiro("tipo") in ("BANCO", "POUPANCA", "APLICACAO") else "BANCO",
        titular=primeiro("titular")[:200],
        inicio=_data(primeiro("inicio")),
        fim=_data(next((p["fim"] for p in reversed(paginas) if str(p.get("fim") or "").strip()), "")),
        exige_conferencia=True,
    )
    lido.saldo_inicial = next((_decimal(p["saldo_inicial"]) for p in paginas if _decimal(p.get("saldo_inicial"))
                               is not None), None)  # fmt: skip
    lido.saldo_final = next(
        (_decimal(p["saldo_final"]) for p in reversed(paginas) if _decimal(p.get("saldo_final")) is not None), None
    )
    if not lido.numero:
        raise ErroLeitura("A IA não achou o número da conta no extrato. Mande o OFX do banco.")

    folga = timedelta(days=7)
    descartados = []
    for pagina in paginas:
        for item in pagina.get("movimentos") or []:
            dia, valor = _data(item.get("data")), _decimal(item.get("valor"))
            fora = dia is None or (lido.inicio and dia < lido.inicio - folga) or (lido.fim and dia > lido.fim + folga)
            if fora or valor is None or valor <= 0 or item.get("sentido") not in ("ENTRADA", "SAIDA"):
                descartados.append(f"{item.get('data')} {item.get('historico')} {item.get('valor')}")
                continue
            lido.movimentos.append(
                MovimentoLido(
                    data=dia,
                    valor=valor,
                    sentido=item["sentido"],
                    historico=" ".join(str(item.get("historico") or "").split())[:120] or "Movimento",
                    complemento=" ".join(str(item.get("complemento") or "").split())[:200],
                    documento=" ".join(str(item.get("documento") or "").split())[:60],
                )
            )
    if not lido.movimentos and lido.saldo_final is None:
        raise ErroLeitura("A IA não encontrou lançamentos no extrato. Mande o OFX do banco.")
    if lido.inicio is None and lido.movimentos:
        lido.inicio = min(m.data for m in lido.movimentos)
    if lido.fim is None and lido.movimentos:
        lido.fim = max(m.data for m in lido.movimentos)
    if descartados:
        lido.avisos.append(Aviso(f"{len(descartados)} linha(s) lidas pela IA ficaram de fora (data ou valor "
                                 "inválido).", descartados))  # fmt: skip
    lido.avisos.append(Aviso("Extrato lido pela IA (este banco ainda não tem leitor próprio). Confira os movimentos."))
    return lido
