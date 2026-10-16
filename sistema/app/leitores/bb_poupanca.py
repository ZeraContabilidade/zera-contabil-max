"""Banco do Brasil — extrato de poupança em PDF (autoatendimento, impresso pelo navegador) (§11.4).

Colunas: Dt. lançamento | Dt. base | Dia | Histórico (código + texto) | Ag. origem | Documento | Informações |
Valor + C/D.
Cada lançamento ocupa até três linhas: o histórico e as informações começam na linha de CIMA da data e terminam
na de BAIXO (“141 Transferencia Para” / “Conta”; “03/08 10:44 CASA C E N S” / “MONTE BERIC”); às vezes o valor
fica numa linha e o C/D em outra. Por isso as linhas são juntadas pela proximidade com a linha da data.

A impressão cortou o saldo anterior (“227.4”): o saldo final vem do cabeçalho (“Saldo: 239.233,33 C”) e a
conferência compara o saldo anterior calculado com os dígitos que dá para ler.
"""

import re
from datetime import datetime
from typing import Any

from app.leitores import ArquivoExtrato, ExtratoLido, MovimentoLido
from app.leitores.ferramentas import DATA, DINHEIRO, linhas, texto_da_linha, valor_br
from app.servicos.contas_chave import normalizar
from app.servicos.plano import Aviso, ErroLeitura

_HORA_NO_COMECO = re.compile(r"^\d{2}/\d{2}\s+\d{2}:\d{2}\s+")
DISTANCIA = 6.5  # linhas a até 6,5 pontos da linha da data são do mesmo lançamento (os lançamentos ficam a ~14)


class _Colunas:
    """Começo de cada coluna (pontos da página), ajustado pelo cabeçalho quando ele aparece."""

    def __init__(self):
        self.base = 100.0  # Dt. base (antes disso: Dt. lançamento)
        self.historico = 165.0
        self.agencia = 273.0
        self.documento = 312.0
        self.informacoes = 355.0
        self.valor = 480.0
        self.sentido = 525.0  # C/D
        self.saldo = 540.0

    def ajustar(self, linha: list[dict[str, Any]]) -> bool:
        textos = [normalizar(p["text"]) for p in linha]
        if "VALOR" not in textos or not any(t.startswith("HISTORIC") for t in textos):
            return False
        posicoes = {}
        for posicao, palavra in enumerate(linha):
            posicoes.setdefault(textos[posicao], palavra["x0"])
            if textos[posicao].startswith("HISTORIC"):
                self.historico = palavra["x0"] - 3
            elif textos[posicao] == "BASE":
                self.base = palavra["x0"] - 15
        if {"AG.", "DOCUMENTO", "INFORMACOES", "SALDO"} <= posicoes.keys():
            # modelo baixado pelas creches: cabeçalho inteiro numa linha e o valor alinhado à ESQUERDA da coluna
            # (o da Casa Criança corta o cabeçalho e alinha o valor à direita: ficam as posições de sempre)
            self.agencia = posicoes["AG."] - 3
            self.documento = posicoes["DOCUMENTO"] - 3
            self.informacoes = posicoes["INFORMACOES"] - 3
            self.valor = posicoes["VALOR"] - 3
            self.sentido = posicoes["VALOR"] + 15  # o C/D vem logo depois do valor (“2,47 C”: bem perto)
            self.saldo = posicoes["SALDO"] - 2
        return True


class LeitorBBPoupanca:
    nome = "Banco do Brasil — poupança (PDF)"

    def reconhece(self, arquivo: ArquivoExtrato) -> bool:
        texto = normalizar(arquivo.texto[:4000])
        if not arquivo.eh_pdf or "EXTRATOS - POUPANCA" not in texto:
            return False
        # o baixado pelas creches não escreve “Banco do Brasil”: vale a variação “POUPANÇA-OURO” do BB
        return "BANCO DO BRASIL" in texto or "POUPANCA-OURO" in texto

    def ler(self, arquivo: ArquivoExtrato) -> ExtratoLido:
        texto = arquivo.texto
        conta = re.search(r"Ag[eê]ncia\s*/\s*Conta\s+(\d{1,5}-[\dXx])\s*/\s*([\d.]+-[\dXx])", texto)
        if not conta:
            raise ErroLeitura("Não achei a agência e a conta no extrato de poupança do Banco do Brasil.")
        titular = re.search(r"Titularidade\s+([^\n]+)", texto)
        lido = ExtratoLido(
            leitor=self.nome,
            banco="Banco do Brasil",
            agencia=conta.group(1),
            numero=conta.group(2).replace(".", ""),
            tipo="POUPANCA",
            titular=" ".join(titular.group(1).split()) if titular else "",
        )
        if periodo := re.search(r"Per[ií]odo\s+(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})", texto):
            lido.inicio, lido.fim = (datetime.strptime(d, "%d/%m/%Y").date() for d in periodo.groups())

        colunas = _Colunas()
        sem_valor: list[str] = []
        saldo_total = ""
        for palavras in arquivo.paginas:
            todas = [linha for linha in linhas(palavras) if not colunas.ajustar(linha)]
            datas = [
                i for i, linha in enumerate(todas) if DATA.match(linha[0]["text"]) and linha[0]["x0"] < colunas.base
            ]
            grupos: dict[int, list[list[dict[str, Any]]]] = {i: [todas[i]] for i in datas}
            for j, linha in enumerate(todas):
                if j in grupos:
                    continue
                if normalizar(texto_da_linha(linha)).startswith("SALDO TOTAL"):
                    # “Saldo total 251.483,54 C”: o número (às vezes cortado: “239.233”), não o C/D do fim
                    com_numero = [p["text"] for p in linha if any(ch.isdigit() for ch in p["text"])]
                    saldo_total = com_numero[-1] if com_numero else ""
                perto = [i for i in datas if abs(todas[i][0]["top"] - linha[0]["top"]) <= DISTANCIA]
                if perto:
                    dono = min(perto, key=lambda i: abs(todas[i][0]["top"] - linha[0]["top"]))
                    grupos[dono].append(linha)
            for i in datas:
                self._grupo(sorted(grupos[i], key=lambda linha: linha[0]["top"]), colunas, lido, sem_valor)

        self._saldo_final(texto, saldo_total, lido)
        if not lido.movimentos:
            raise ErroLeitura("Não encontrei lançamentos no extrato de poupança. Confira se o PDF está completo.")
        if lido.inicio is None:
            lido.inicio = min(m.data for m in lido.movimentos)
            lido.fim = max(m.data for m in lido.movimentos)
        if sem_valor:
            lido.avisos.append(
                Aviso(f"{len(sem_valor)} linha(s) sem valor ou sem C/D foram ignoradas. Confira no PDF.", sem_valor)
            )
        return lido

    def _grupo(self, grupo: list[list[dict[str, Any]]], colunas: _Colunas, lido: ExtratoLido, sem_valor: list[str]):
        palavras = [p for linha in grupo for p in linha]
        data = next(datetime.strptime(p["text"], "%d/%m/%Y").date() for p in palavras if p["x0"] < colunas.base)
        historico = [p["text"] for p in palavras if colunas.historico <= p["x0"] < colunas.agencia]
        documento = [p["text"] for p in palavras if colunas.documento <= p["x0"] < colunas.informacoes]
        informacoes = [p["text"] for p in palavras if colunas.informacoes <= p["x0"] < colunas.valor]
        valores = [p for p in palavras if p["x0"] >= colunas.valor and DINHEIRO.match(p["text"])]
        lado = [p for p in palavras if colunas.sentido <= p["x0"] < colunas.saldo]
        sentido = [p["text"] for p in lado if p["text"] in ("C", "D")]
        saldo = [p["text"] for p in palavras if p["x0"] >= colunas.saldo]

        codigo = historico.pop(0) if historico and re.fullmatch(r"\d{3}", historico[0]) else ""
        texto_historico = " ".join(historico)
        if normalizar(texto_historico) == "SALDO ANTERIOR":
            self._saldo_anterior(saldo[0] if saldo else "", lido)
            return
        if not valores or not sentido:
            sem_valor.append(f"{data:%d/%m/%Y} {texto_historico}")
            return
        lido.movimentos.append(
            MovimentoLido(
                data=data,
                valor=valor_br(valores[0]["text"]),
                sentido="ENTRADA" if sentido[0] == "C" else "SAIDA",
                historico=texto_historico[:120],
                complemento=_HORA_NO_COMECO.sub("", " ".join(informacoes)).strip()[:200],
                documento=" ".join(documento)[:60],
                codigo=codigo,
            )
        )

    def _saldo_anterior(self, texto: str, lido: ExtratoLido) -> None:
        if DINHEIRO.match(texto):
            lido.saldo_inicial = valor_br(texto)
        else:
            lido.saldo_inicial_visivel = texto  # cortado na impressão: “227.4”

    def _saldo_final(self, texto: str, saldo_total: str, lido: ExtratoLido) -> None:
        """O saldo do cabeçalho é o de hoje; só vale como saldo final se bater com o “Saldo total” do fim
        do extrato (que a impressão também corta: “239.233”)."""
        if DINHEIRO.match(saldo_total):
            lido.saldo_final = valor_br(saldo_total)
            return
        cabecalho = re.search(r"Saldo:\s*([\d.]+,\d{2})\s*([CD])?", texto)
        if not cabecalho:
            return
        final = valor_br(cabecalho.group(1))
        if cabecalho.group(2) == "D":
            final = -final
        if not saldo_total or cabecalho.group(1).startswith(saldo_total):
            lido.saldo_final = final
        else:
            lido.avisos.append(
                Aviso(
                    "O saldo do alto do extrato é de outra data (não bate com o saldo total do fim): "
                    "a conferência do saldo ficou de fora."
                )
            )
