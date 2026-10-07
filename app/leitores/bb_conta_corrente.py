"""Banco do Brasil — extrato de conta corrente em PDF (autoatendimento, impresso pelo navegador) (§11.4).

Colunas: Dt. balancete | Ag. origem | Lote | Histórico (código + texto) | Documento | Valor R$ (+ C/D) | Saldo.
O favorecido vem numa 2ª linha (“05/08 08:55 CASA C E N S MONTE BERIC” ou só “SABESP”).
A impressão cortou a coluna Saldo (“0,” no lugar de “0,00”) e às vezes joga o valor ou o C/D para a
linha de baixo: por isso a leitura é pela POSIÇÃO das palavras, não pelo texto corrido.
"""

import calendar
import re
from datetime import date, datetime
from typing import Any

from app.leitores import ArquivoExtrato, ExtratoLido, MovimentoLido
from app.leitores.ferramentas import DATA, linhas, saldo_br, texto_da_linha, valor_br
from app.servicos.contas_chave import normalizar
from app.servicos.plano import Aviso, ErroLeitura

_HORA_NO_COMECO = re.compile(r"^\d{2}/\d{2}\s+\d{2}:\d{2}\s+")
_DOCUMENTO = re.compile(r"^[\d.\-/]+$")


class _Colunas:
    """Onde ficam as colunas, pelo cabeçalho da 1ª página (as outras páginas não repetem o cabeçalho)."""

    def __init__(self):
        self.historico = 220.0  # começo do Histórico
        self.valor_fim = 528.0  # fim do Valor R$ (os valores são alinhados à direita)
        self.saldo = 556.0  # começo do Saldo

    def ajustar(self, linha: list[dict[str, Any]]) -> bool:
        textos = [normalizar(p["text"]) for p in linha]
        if "VALOR" not in textos or "DOCUMENTO" not in textos:
            return False
        for posicao, palavra in enumerate(linha):
            texto = textos[posicao]
            if texto.startswith("HISTORIC"):
                self.historico = palavra["x0"] - 4
            elif texto in ("VALOR", "R$"):
                self.valor_fim = palavra["x1"] + 3
            elif posicao == len(linha) - 1 and palavra["x0"] > self.valor_fim:
                self.saldo = palavra["x0"] - 10  # “Saldo”, cortado para “S” na impressão
        return True


class LeitorBBContaCorrente:
    nome = "Banco do Brasil — conta corrente (PDF)"

    def reconhece(self, arquivo: ArquivoExtrato) -> bool:
        texto = normalizar(arquivo.texto[:4000])
        return arquivo.eh_pdf and "BANCO DO BRASIL" in texto and "EXTRATO DE CONTA CORRENTE" in texto

    def ler(self, arquivo: ArquivoExtrato) -> ExtratoLido:
        texto = arquivo.texto
        agencia = re.search(r"Ag[eê]ncia\s+(\d{1,5}-[\dXx])", texto)
        conta = re.search(r"Conta corrente\s+([\d.]+-[\dXx])\s+([^\n]*)", texto)
        if not agencia or not conta:
            raise ErroLeitura("Não achei a agência e a conta no extrato do Banco do Brasil. Baixe o PDF de novo.")
        lido = ExtratoLido(
            leitor=self.nome,
            banco="Banco do Brasil",
            agencia=agencia.group(1),
            numero=conta.group(1).replace(".", ""),
            tipo="BANCO",
            titular=" ".join(conta.group(2).split()),
        )
        if periodo := re.search(r"Per[ií]odo do\s+(\d{2})\s*/\s*(\d{4})", texto):
            mes, ano = int(periodo.group(1)), int(periodo.group(2))
            lido.inicio = date(ano, mes, 1)
            lido.fim = date(ano, mes, calendar.monthrange(ano, mes)[1])

        colunas = _Colunas()
        pendente: dict[str, Any] | None = None
        sem_valor: list[str] = []
        todas = [linha for palavras in arquivo.paginas for linha in linhas(palavras)]
        for linha in todas:
            if colunas.ajustar(linha):
                continue
            primeira = linha[0]
            if DATA.match(primeira["text"]) and primeira["x0"] < colunas.historico:
                self._fechar(pendente, lido, sem_valor)
                pendente = self._lancamento(linha, colunas)
                if "saldo_final" in pendente:
                    break  # depois do SALDO final vêm só observações
            elif pendente and primeira["x0"] >= colunas.historico - 5 and not primeira["text"].startswith("http"):
                self._continuacao(linha, pendente, colunas)
        self._fechar(pendente, lido, sem_valor)

        if not lido.movimentos and lido.saldo_final is None:
            raise ErroLeitura(
                "Não encontrei lançamentos no extrato do Banco do Brasil. Confira se o PDF está completo."
            )
        if lido.inicio is None and lido.movimentos:
            lido.inicio = min(m.data for m in lido.movimentos)
            lido.fim = max(m.data for m in lido.movimentos)
        if sem_valor:
            lido.avisos.append(
                Aviso(f"{len(sem_valor)} linha(s) sem valor ou sem C/D foram ignoradas. Confira no PDF.", sem_valor)
            )
        return lido

    def _lancamento(self, linha: list[dict[str, Any]], colunas: _Colunas) -> dict[str, Any]:
        data = datetime.strptime(linha[0]["text"], "%d/%m/%Y").date()
        meio = [p for p in linha if colunas.historico <= p["x0"] and p["x1"] <= colunas.valor_fim]
        saldo = [p for p in linha if p["x0"] >= colunas.saldo]
        item: dict[str, Any] = {"data": data, "valor": None, "sentido": None, "documento": "", "complemento": []}
        if meio and re.fullmatch(r"\d{3}", meio[0]["text"]):
            item["codigo"] = meio.pop(0)["text"]
        self._valor_e_sentido(meio, item, colunas)
        if meio and _DOCUMENTO.match(meio[-1]["text"]) and any(ch.isdigit() for ch in meio[-1]["text"]):
            item["documento"] = meio.pop()["text"]
        item["historico"] = " ".join(p["text"] for p in meio)
        titulo = normalizar(item["historico"]).replace(" ", "")
        if titulo in ("SALDOANTERIOR", "SALDO"):
            lido_saldo = saldo_br(saldo[0]["text"]) if saldo else None
            item["saldo_final" if titulo == "SALDO" else "saldo_inicial"] = lido_saldo or (None, False)
        return item

    def _valor_e_sentido(self, palavras: list[dict[str, Any]], item: dict[str, Any], colunas: _Colunas) -> None:
        """Tira das palavras o valor (alinhado à direita na coluna Valor) e o C/D logo depois dele."""
        for palavra in list(palavras):
            texto = palavra["text"]
            if item["valor"] is None and valor_br(texto) is not None and palavra["x1"] > colunas.valor_fim - 60:
                item["valor"] = valor_br(texto)
                palavras.remove(palavra)
            elif item["sentido"] is None and texto in ("C", "D") and palavra["x0"] > colunas.valor_fim - 20:
                item["sentido"] = "ENTRADA" if texto == "C" else "SAIDA"
                palavras.remove(palavra)

    def _continuacao(self, linha: list[dict[str, Any]], item: dict[str, Any], colunas: _Colunas) -> None:
        """2ª linha do lançamento: o favorecido; às vezes também o valor ou o C/D que caíram para baixo."""
        palavras = [p for p in linha if p["x1"] <= colunas.valor_fim]
        if item["valor"] is None or item["sentido"] is None:
            self._valor_e_sentido(palavras, item, colunas)
        if texto := _HORA_NO_COMECO.sub("", texto_da_linha(palavras)).strip():
            item["complemento"].append(texto)

    def _fechar(self, item: dict[str, Any] | None, lido: ExtratoLido, sem_valor: list[str]) -> None:
        if item is None:
            return
        if "saldo_inicial" in item or "saldo_final" in item:
            valor, cortado = item.get("saldo_inicial") or item.get("saldo_final")
            if valor is not None:
                setattr(lido, "saldo_inicial" if "saldo_inicial" in item else "saldo_final", valor)
                lido.saldo_cortado = lido.saldo_cortado or cortado
            return
        if item["valor"] is None or item["sentido"] is None:
            sem_valor.append(f"{item['data']:%d/%m/%Y} {item['historico']}")
            return
        lido.movimentos.append(
            MovimentoLido(
                data=item["data"],
                valor=item["valor"],
                sentido=item["sentido"],
                historico=item["historico"][:120],
                complemento=" ".join(item["complemento"])[:200],
                documento=item["documento"][:60],
                codigo=item.get("codigo", ""),
            )
        )
