"""Monta Diários de teste no layout do Domínio (Excel), com dados fictícios.

Mesmas posições do Diário real: Data (A), Classificação (D), Descrição (F), Histórico (I), Débito (N), Crédito (R);
cabeçalho com Empresa / C.N.P.J. / Período, “TOTAL DO DIA” depois de cada dia e o rodapé com as assinaturas.
"""

import io
from datetime import datetime
from decimal import Decimal
from itertools import groupby

from openpyxl import Workbook

CNPJ_EXEMPLO = "12.345.678/0001-95"  # fictício, com dígito válido
COLUNAS = {"data": 1, "classificacao": 4, "descricao": 6, "historico": 9, "debito": 14, "credito": 18}


def montar_diario(lancamentos, empresa="ASSOCIACAO CRECHE EXEMPLO", cnpj=CNPJ_EXEMPLO, periodo="") -> bytes:
    """lancamentos = [("30/01/2026", "2.1.5.01.000001", "SALÁRIOS A PAGAR", "histórico", "D", "2861.25"), ...]"""
    planilha = Workbook()
    aba = planilha.active
    aba.title = "Diário"
    aba.append(["Empresa:", None, empresa, None, None, None, None, None, None, None, None, "Folha:", 1])
    aba.append(["C.N.P.J.:", None, cnpj, None, None, None, None, None, None, None, None, "Número livro:", 1])
    aba.append(["Período:", None, periodo or "01/01/2026 - 30/06/2026"])
    aba.append([])
    aba.append(["DIÁRIO"])
    aba.append([])
    nomes = {"data": "Data", "classificacao": "Classificação", "descricao": "Descrição", "historico": "Histórico"}
    nomes |= {"debito": "Débito", "credito": "Crédito"}
    for nome, coluna in COLUNAS.items():
        aba.cell(7, coluna, nomes[nome])
    linha = 8
    for _, do_dia in groupby(lancamentos, key=lambda item: item[0]):
        debito = credito = Decimal("0")
        for data, classificacao, descricao, historico, lado, valor in do_dia:
            linha += 1
            aba.cell(linha, COLUNAS["data"], datetime.strptime(data, "%d/%m/%Y"))
            aba.cell(linha, COLUNAS["classificacao"], classificacao)
            aba.cell(linha, COLUNAS["descricao"], descricao)
            aba.cell(linha, COLUNAS["historico"], historico)
            aba.cell(linha, COLUNAS["debito" if lado == "D" else "credito"], float(valor))
            debito += Decimal(valor) if lado == "D" else 0
            credito += Decimal(valor) if lado == "C" else 0
        linha += 1
        aba.cell(linha, 12, "TOTAL DO DIA")
        aba.cell(linha, COLUNAS["debito"], float(debito))
        aba.cell(linha, COLUNAS["credito"], float(credito))
        linha += 1
    aba.cell(linha + 2, 1, f"\n____________\n{empresa}\nCNPJ: {cnpj}")
    aba.cell(linha + 5, 1, "Sistema licenciado para ESCRITORIO EXEMPLO")
    saida = io.BytesIO()
    planilha.save(saida)
    return saida.getvalue()


BANCO = ("1.1.1.02.000001", "BCO BRASIL CC 12345-6")
POUPANCA = ("1.1.1.03.000001", "POUPANÇA BB 12345-6")

# Diário completo (todas as contas), no plano de tests/planos.py
DIARIO_COMPLETO = [
    # o mesmo pagamento de água e de FGTS que está no lanctos_exemplo.txt
    ("05/03/2026", "3.2.2.04.000002", "ÁGUA E ESGOTO",
     "COMPANHIA DE AGUA EXEMPLO - 44.555.666/0001-81 - CONTA DE AGUA - S/N", "D", "101.30"),
    ("05/03/2026", *BANCO, "COMPANHIA DE AGUA EXEMPLO - 44.555.666/0001-81 - CONTA DE AGUA - S/N", "C", "101.30"),
    ("10/03/2026", "2.1.5.02.000002", "FGTS A RECOLHER",
     "PAGAMENTO DA GUIA DE FGTS - REF S FOLHA DE FEVEREIRO - S/N", "D", "850.00"),
    ("10/03/2026", *BANCO, "PAGAMENTO DA GUIA DE FGTS - REF S FOLHA DE FEVEREIRO - S/N", "C", "850.00"),
    # folha: um débito contra dois créditos, sem banco
    ("15/03/2026", "3.2.2.01.000001", "SALÁRIOS E ORDENADOS", "FOLHA DE PAGAMENTO 03/2026", "D", "5000.00"),
    ("15/03/2026", "2.1.5.01.000001", "SALÁRIOS E ORDENADOS A PAGAR", "FOLHA DE PAGAMENTO 03/2026", "C", "4500.00"),
    ("15/03/2026", "2.1.5.02.000001", "INSS/PIS/IRRF/RAT A RECOLHER", "FOLHA DE PAGAMENTO 03/2026", "C", "500.00"),
    # classificação usada por duas contas no plano (10594 e 10595): decide pela descrição
    ("25/03/2026", "3.2.2.04.000017", "CONTRIBUIÇÃO NEGOCIAL",
     "SINDICATO EXEMPLO 11.222.333/0001-81 - CONTRIBUIÇÃO NEGOCIAL - S/N", "D", "247.50"),
    ("25/03/2026", *BANCO, "SINDICATO EXEMPLO 11.222.333/0001-81 - CONTRIBUIÇÃO NEGOCIAL - S/N", "C", "247.50"),
    # rendimento da poupança: recebimento
    ("31/03/2026", *POUPANCA, "RENDIMENTO DA POUPANCA", "D", "12.34"),
    ("31/03/2026", "4.6.1.02.000001", "RENDIMENTOS C/APLIC FINANC", "RENDIMENTO DA POUPANCA", "C", "12.34"),
]  # fmt: skip

# Diário impresso só com o Passivo (grupo 2): os dias não fecham
DIARIO_SO_PASSIVO = [
    ("30/01/2026", "2.1.5.01.000001", "SALÁRIOS E ORDENADOS A PAGAR",
     "MARIA SOUZA  - SALARIO MENSAL  - S/N", "D", "2861.25"),  # pago pelo banco (também no lanctos_exemplo)
    ("30/01/2026", "2.1.5.01.000001", "SALÁRIOS E ORDENADOS A PAGAR",
     "REMUNERACOES CONF. FOLHA DE PAGAMENTO REF. 01/2026", "C", "1909.04"),  # provisão: não é do extrato
    ("30/01/2026", "2.1.5.01.000001", "SALÁRIOS E ORDENADOS A PAGAR",
     "VALOR A SER RECOLHIDO DE INSS REF. 01/2026", "D", "147.49"),  # os dois lados estão no arquivo
    ("30/01/2026", "2.1.5.02.000001", "INSS/PIS/IRRF/RAT A RECOLHER",
     "VALOR A SER RECOLHIDO  DE INSS REF. 01/2026", "C", "147.49"),
    ("10/02/2026", "2.1.3.01.000193", "PAPELARIA CENTRAL", "AQUISICAO CONFORME NOTA FISCAL", "C", "334.94"),
    ("12/02/2026", "2.1.3.01.000193", "PAPELARIA CENTRAL",
     "PAPELARIA CENTRAL - 55.667.788/0001-86 - MATERIAL DE ESCRITORIO (FEVEREIRO) - 5841", "D", "334.94"),
]  # fmt: skip
