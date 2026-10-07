"""Leitores de extrato (§3.4): um arquivo por banco e formato, todos neste registro.

Para um banco novo: crie `app/leitores/<banco>_<tipo>.py` com uma classe que tenha `nome`,
`reconhece(arquivo)` e `ler(arquivo)` e acrescente-a em `LEITORES` (no fim deste arquivo).
O primeiro leitor que reconhecer o arquivo é usado; a detecção é sempre pelo CONTEÚDO, nunca pelo nome.
"""

import io
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Any, Protocol

import pdfplumber

from app.servicos.plano import Aviso, ErroLeitura, decodificar

logging.getLogger("pdfminer").setLevel(logging.ERROR)  # avisos de fonte dos PDFs do banco: não interessam


@dataclass
class MovimentoLido:
    data: date
    valor: Decimal  # sempre positivo
    sentido: str  # ENTRADA ou SAIDA
    historico: str  # como o banco escreve: “Pagamento de Boleto”
    complemento: str = ""  # 2ª linha do banco: favorecido ou pagador
    documento: str = ""
    codigo: str = ""  # código do histórico no banco


@dataclass
class ExtratoLido:
    leitor: str
    banco: str  # nome do banco, para identificar_banco()
    agencia: str
    numero: str
    tipo: str  # BANCO (conta corrente), POUPANCA ou APLICACAO
    titular: str = ""
    inicio: date | None = None
    fim: date | None = None
    saldo_inicial: Decimal | None = None
    saldo_final: Decimal | None = None
    saldo_cortado: bool = False  # o PDF cortou os centavos (e o sinal) do saldo
    saldo_inicial_visivel: str = ""  # saldo anterior cortado na impressão (“227.4”): confere pelo começo
    movimentos: list[MovimentoLido] = field(default_factory=list)
    avisos: list[Aviso] = field(default_factory=list)


@dataclass
class ArquivoExtrato:
    """O arquivo enviado. O PDF é aberto uma vez só, para todos os leitores."""

    nome: str
    conteudo: bytes

    @property
    def eh_pdf(self) -> bool:
        return self.conteudo.lstrip()[:5] == b"%PDF-"

    @cached_property
    def _pdf(self) -> tuple[list[str], list[list[dict[str, Any]]]]:
        if not self.eh_pdf:
            return [], []
        try:
            with pdfplumber.open(io.BytesIO(self.conteudo)) as pdf:
                textos = [pagina.extract_text() or "" for pagina in pdf.pages]
                palavras = [pagina.extract_words() for pagina in pdf.pages]
        except Exception as erro:
            raise ErroLeitura("Não consegui abrir o PDF. Baixe o extrato de novo no internet banking.") from erro
        return textos, palavras

    @property
    def paginas(self) -> list[list[dict[str, Any]]]:
        """Palavras de cada página, com a posição (x0, x1, top) — para ler pelas colunas."""
        return self._pdf[1]

    @cached_property
    def texto(self) -> str:
        return "\n".join(self._pdf[0]) if self.eh_pdf else decodificar(self.conteudo)


class Leitor(Protocol):
    nome: str

    def reconhece(self, arquivo: ArquivoExtrato) -> bool: ...
    def ler(self, arquivo: ArquivoExtrato) -> ExtratoLido: ...


def ler_extrato(nome: str, conteudo: bytes) -> ExtratoLido:
    arquivo = ArquivoExtrato(nome, conteudo)
    if arquivo.eh_pdf and not arquivo.texto.strip():
        raise ErroLeitura(
            f"O PDF “{nome}” não tem texto (parece uma foto ou digitalização). Baixe o extrato em PDF pelo "
            "internet banking ou em OFX. O leitor com IA para estes casos chega numa próxima etapa."
        )
    for leitor in LEITORES:
        if leitor.reconhece(arquivo):
            return leitor.ler(arquivo)
    raise ErroLeitura(
        f"Não reconheci o extrato “{nome}”. Por enquanto o sistema lê os PDFs do Banco do Brasil (conta "
        "corrente e poupança); OFX, Excel e outros bancos chegam nas próximas etapas."
    )


# o registro vem depois dos tipos, que os leitores usam
from app.leitores.bb_conta_corrente import LeitorBBContaCorrente  # noqa: E402
from app.leitores.bb_poupanca import LeitorBBPoupanca  # noqa: E402

LEITORES: list[Leitor] = [LeitorBBContaCorrente(), LeitorBBPoupanca()]
