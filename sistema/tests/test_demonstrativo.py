"""Demonstrativo da prestação de contas (15/10/2026): o leitor (colunas pelos títulos, lista de apoio à direita
ignorada, cabeçalho repetido, total conferido) e o cruzamento com o extrato — cada linha do banco ganha o favorecido de
verdade, o CNPJ, o que foi pago e o nº da nota; a transferência do rateio é desdobrada em um lançamento por guia."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.leitores import ExtratoLido, MovimentoLido
from app.leitores.demonstrativo import e_demonstrativo, ler_demonstrativo
from app.modelos import ContaBancaria, Empresa, LinhaDemonstrativo, MovimentoExtrato
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.demonstrativos import importar_demonstrativo, situacao_do_mes
from app.servicos.extratos import importar_extrato
from app.servicos.plano import ErroLeitura
from tests.conftest import AMOSTRAS, entrar
from tests.demonstrativos import montar_demonstrativo
from tests.planos import criar_plano

PAGAMENTOS = [
    {"favorecido": "SINDICATO EXEMPLO 11.444.777/0001-61", "especificacao": "PLANO ODONTOLOGICO", "tipo": "BOLETO",
     "data_doc": datetime(2026, 8, 10), "transf": 80302, "data": datetime(2026, 8, 3), "valor": 845.0,
     "grupo": "Recursos Humanos "},
    {"favorecido": "MARIA DE SOUZA", "especificacao": "SALÁRIO MENSAL", "tipo": "HOLERITE",
     "transf": 612180000066236, "data": datetime(2026, 8, 25), "valor": 1797.09},
    {"favorecido": "RATEIO PARA PAGAMENTO - FGTS", "especificacao": "REF S FOLHA JULHO", "tipo": "GFD",
     "transf": 611819000073000, "data": datetime(2026, 8, 14), "valor": 3865.94, "grupo": "Encargos",
     "cabecalho_antes": True},
    {"favorecido": "RATEIO PARA PAGAMENTO - FGTS CONSIGNADO", "especificacao": "REF S FOLHA JULHO", "tipo": "GFD",
     "transf": 611819000073000, "data": datetime(2026, 8, 14), "valor": 3217.33},
    {"favorecido": "PADARIA EXEMPLO - 11.222.333/0001-81", "especificacao": "MARMITAS", "numero": 92,
     "transf": 83101, "data": datetime(2026, 8, 31), "valor": 4095.0, "grupo": "Materiais"},
    {"favorecido": "LOJA SEM EXTRATO", "especificacao": "MAT. DE LIMPEZA (SABÃO)", "numero": 12440,
     "transf": 99999, "data": datetime(2026, 8, 20), "valor": 50.0},
]  # fmt: skip


# ---------------------------------------------------------------- leitor (sem banco)


def test_le_o_demonstrativo_pelos_titulos():
    lido = ler_demonstrativo("demonstrativo.xlsx", montar_demonstrativo(PAGAMENTOS))
    assert (lido.agencia, lido.contas, lido.mes, lido.creche) == (
        "1234-5",
        ["12345-6"],
        date(2026, 8, 1),
        "Creche Exemplo",
    )
    assert lido.cnpj == "11222333000181"
    assert len(lido.pagamentos) == 6 and not lido.avisos  # o total confere; o “TOTAL” da conciliação não atrapalha
    sindicato, maria, fgts, consignado, padaria, _ = lido.pagamentos
    assert (sindicato.nome, sindicato.cnpj_cpf, sindicato.transferencia) == (
        "SINDICATO EXEMPLO",
        "11444777000161",
        "80302",
    )
    assert (sindicato.grupo, sindicato.documento_tipo, sindicato.data) == (
        "Recursos Humanos",
        "BOLETO",
        date(2026, 8, 3),
    )
    assert sindicato.documento_numero == "" and padaria.documento_numero == "92"  # S/N fica vazio
    assert (fgts.grupo, consignado.grupo, consignado.valor) == ("Encargos", "Encargos", Decimal("3217.33"))
    assert maria.grupo == "Recursos Humanos" and padaria.grupo == "Materiais"
    repasse = lido.receitas[0]
    assert (repasse.especificacao, repasse.valor, repasse.transferencia) == (
        "REPASSE MUNICIPAL",
        Decimal("90000.00"),
        "556882000051019",
    )
    assert repasse.data == date(2026, 8, 11) and lido.rendimento == Decimal("10.50")


def test_outras_receitas_com_documento_e_duas_contas():
    outras = "OUTRAS RECEITAS - TRANSF. RECEBIDA DA CRECHE EXEMPLO - DOC 611.819.000.078.640 - 14/08/2026"
    receitas = [("REPASSE MUNICIPAL", 72000.0), (outras, 7083.27)]
    conteudo = montar_demonstrativo(PAGAMENTOS[:1], receitas, conta="AG: 1234-5 C.C Nº: 53.215-0 e 73000-9")
    lido = ler_demonstrativo("d.xlsx", conteudo)
    assert lido.contas == ["53215-0", "73000-9"]
    outra = lido.receitas[1]
    assert (outra.valor, outra.transferencia, outra.data) == (Decimal("7083.27"), "611819000078640", date(2026, 8, 14))


def test_reconhece_so_o_demonstrativo():
    from io import BytesIO

    from openpyxl import Workbook

    assert e_demonstrativo(montar_demonstrativo(PAGAMENTOS))
    planilha = BytesIO()
    Workbook().save(planilha)
    assert not e_demonstrativo(planilha.getvalue())
    assert not e_demonstrativo(b"%PDF-1.4")
    with pytest.raises(ErroLeitura, match="BLOCO 4"):
        ler_demonstrativo("outra.xlsx", planilha.getvalue())


@pytest.mark.amostras
def test_demonstrativos_reais_somam_o_total_das_despesas():
    arquivos = sorted((AMOSTRAS).glob("DEMONSTRATIVOS */**/demonstrativo.xlsx"))
    if not arquivos:
        pytest.skip("AMOSTRAS/ não está neste computador")
    for arquivo in arquivos:
        lido = ler_demonstrativo(arquivo.name, arquivo.read_bytes())
        assert lido.total_despesas == sum(p.valor for p in lido.pagamentos), arquivo
        assert lido.contas and lido.mes == date(2026, 8, 1) and not lido.avisos, arquivo


# ---------------------------------------------------------------- cruzamento com o extrato (com banco)

HISTORICO = "\r\n".join(
    [f"05/{mes:02d}/2026;10594;8;845,00;;SINDICATO EXEMPLO 11.444.777/0001-61 - PLANO ODONTOLOGICO - S/N;1;230;;"
     for mes in (5, 6, 7)]
    + [f"25/{mes:02d}/2026;331;8;1797,09;;MARIA DE SOUZA - SALÁRIO MENSAL - S/N;1;230;;" for mes in (5, 6, 7)]
    + [f"20/{mes:02d}/2026;192;8;3865,94;;RATEIO PARA PAGAMENTO DO FGTS - REF S FOLHA (JUNHO) - S/N;1;230;;"
       for mes in (6, 7)]
).encode("cp1252")  # fmt: skip


def _mov(dia, valor, sentido, historico, complemento, documento=""):
    return MovimentoLido(date(2026, 8, dia), Decimal(valor), sentido, historico, complemento, documento)


EXTRATO = ExtratoLido(
    leitor="teste",
    banco="Banco do Brasil",
    agencia="1234-5",
    numero="12345-6",
    tipo="BANCO",
    titular="ASSOCIACAO EXEMPLO",
    inicio=date(2026, 8, 1),
    fim=date(2026, 8, 31),
    movimentos=[
        _mov(3, "845.00", "SAIDA", "Pix - Enviado", "LYTEX", "80.302"),
        _mov(10, "12.50", "SAIDA", "Tarifa Pacote de Serviços", ""),
        _mov(11, "90000.00", "ENTRADA", "Transferência recebida", "PREFEITURA EXEMPLO", "556.882.000.051.019"),
        _mov(14, "7083.27", "SAIDA", "Transferência enviada", "ASSOCIACAO EXEMPLO", "611.819.000.073.000"),
        _mov(15, "77.00", "SAIDA", "Pix - Enviado", "FULANO DESCONHECIDO", "81.501"),
        _mov(25, "1797.09", "SAIDA", "Transferência enviada", "MARIA SOUZA", "612.180.000.066.236"),
        _mov(31, "4095.00", "SAIDA", "Pix - Enviado", "SABOR DA FAMILIA", "83.101"),
    ],
)


@pytest.fixture
def creche(sessao, criar_usuario, cliente, monkeypatch):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Exemplo")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    importar_historico(sessao, nova, "lanctos.txt", HISTORICO, None)
    aprender(sessao, nova)
    sessao.commit()
    monkeypatch.setattr("app.servicos.extratos.ler_extrato", lambda nome, conteudo: EXTRATO)
    return nova


def _sugestao(sessao, complemento: str):
    movimento = sessao.scalar(
        select(MovimentoExtrato).where(
            MovimentoExtrato.complemento == complemento, MovimentoExtrato.desdobrado.is_(False)
        )
    )
    return movimento.sugestao


@pytest.mark.banco
def test_demonstrativo_da_o_favorecido_a_natureza_e_desdobra_o_rateio(sessao, creche):
    importar_extrato(sessao, creche, "cc.pdf", b"%PDF-", None)
    importacao = importar_demonstrativo(sessao, creche, "demonstrativo.xlsx", montar_demonstrativo(PAGAMENTOS), None)
    sessao.commit()
    resumo = importacao.resumo
    assert (resumo["pagamentos"], resumo["ligadas"], resumo["desdobradas"], resumo["partes"]) == (6, 6, 1, 2)

    # o banco escreveu “LYTEX”: o demonstrativo diz que é o plano odontológico do sindicato (e a conta vem daí)
    lytex = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == "LYTEX")).sugestao
    assert (lytex.conta_debito.reduzido, lytex.origem, lytex.status) == (10594, "DEMONSTRATIVO", "APROVADO")
    assert lytex.complemento == "SINDICATO EXEMPLO 11.444.777/0001-61 - PLANO ODONTOLOGICO - S/N"
    maria = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == "MARIA SOUZA")).sugestao
    assert (maria.conta_debito.reduzido, maria.complemento) == (331, "MARIA DE SOUZA - SALÁRIO MENSAL - S/N")
    padaria = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == "SABOR DA FAMILIA")).sugestao
    assert padaria.complemento == "PADARIA EXEMPLO - 11.222.333/0001-81 - MARMITAS - 92"  # o nº da nota no fim
    assert padaria.status == "PENDENTE"  # “MARMITAS” nunca apareceu no histórico: fica para escolher

    # rateio: a transferência de 7.083,27 vira FGTS + FGTS consignado, cada um com o seu lançamento
    original = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.valor == Decimal("7083.27")))
    assert original.desdobrado and original.sugestao is None
    partes = sessao.scalars(select(MovimentoExtrato).where(MovimentoExtrato.parte_de_id == original.id)).all()
    assert sorted(p.valor for p in partes) == [Decimal("3217.33"), Decimal("3865.94")]
    fgts = next(p for p in partes if p.valor == Decimal("3865.94")).sugestao
    assert (fgts.conta_debito.reduzido, fgts.conta_credito.reduzido) == (192, 8)
    assert fgts.complemento == "RATEIO PARA PAGAMENTO - FGTS - REF S FOLHA JULHO - S/N"

    situacao = situacao_do_mes(sessao, creche, date(2026, 8, 1))
    assert [linha.nome for linha in situacao.sem_extrato] == ["LOJA SEM EXTRATO"]
    assert [m.complemento for m in situacao.sem_demonstrativo] == ["FULANO DESCONHECIDO"]  # a tarifa não conta


@pytest.mark.banco
def test_mandar_de_novo_troca_o_anterior_sem_duplicar(sessao, creche):
    importar_extrato(sessao, creche, "cc.pdf", b"%PDF-", None)
    importar_demonstrativo(sessao, creche, "d.xlsx", montar_demonstrativo(PAGAMENTOS), None)
    sessao.commit()
    # as linhas do banco ficam na memória, lembrando das linhas do demonstrativo antigo (que vão ser apagadas)
    na_memoria = list(sessao.scalars(select(MovimentoExtrato)))
    assert sum(m.linha_demonstrativo is not None for m in na_memoria) == 6  # 4 linhas + as 2 partes do rateio
    corrigido = [p for p in PAGAMENTOS if "LOJA" not in p["favorecido"]]
    corrigido[0] = {**corrigido[0], "especificacao": "MENSALIDADE SINDICAL"}  # o cliente corrigiu uma linha
    importacao = importar_demonstrativo(sessao, creche, "d2.xlsx", montar_demonstrativo(corrigido), None)
    sessao.commit()
    assert sessao.scalar(select(func.count()).select_from(LinhaDemonstrativo)) == 6  # 5 pagamentos + o repasse
    assert sessao.scalar(select(func.count()).where(MovimentoExtrato.parte_de_id.is_not(None))) == 2
    assert importacao.resumo["sem_extrato"] == 0 and importacao.resumo["ligadas"] == 6
    assert "MENSALIDADE SINDICAL" in _sugestao(sessao, "LYTEX").complemento  # vale o demonstrativo novo


@pytest.mark.banco
def test_extrato_que_chega_depois_liga_as_linhas(sessao, creche):
    importacao = importar_demonstrativo(sessao, creche, "d.xlsx", montar_demonstrativo(PAGAMENTOS), None)
    sessao.commit()
    assert importacao.resumo["ligadas"] == 0
    assert any("ainda não está no sistema" in aviso["texto"] for aviso in importacao.avisos)
    importar_extrato(sessao, creche, "cc.pdf", b"%PDF-", None)
    sessao.commit()
    assert situacao_do_mes(sessao, creche, date(2026, 8, 1)).ligadas == 6
    assert _sugestao(sessao, "LYTEX").origem == "DEMONSTRATIVO"


@pytest.mark.banco
def test_demonstrativo_de_outra_creche_e_recusado(sessao, creche):
    outra = Empresa(codigo_dominio=121, nome_curto="Outra Creche")
    sessao.add(outra)
    sessao.flush()
    sessao.add(ContaBancaria(empresa_id=outra.id, banco_codigo="001", banco_nome="Banco do Brasil", agencia="1234-5",
                             numero="12345-6", tipo="BANCO"))  # fmt: skip
    sessao.commit()
    with pytest.raises(ErroLeitura, match="Outra Creche"):
        importar_demonstrativo(sessao, creche, "d.xlsx", montar_demonstrativo(PAGAMENTOS), None)


@pytest.mark.banco
def test_enviar_pela_tela_junto_com_o_extrato(sessao, creche, cliente):
    arquivos = [
        ("arquivos", ("demonstrativo.xlsx", montar_demonstrativo(PAGAMENTOS), "application/octet-stream")),
        ("arquivos", ("cc.pdf", b"%PDF-1.4", "application/pdf")),
    ]
    resposta = cliente.post(f"/empresas/{creche.id}/extratos", files=arquivos, follow_redirects=True)
    assert resposta.status_code == 200
    assert "demonstrativo de agosto" in resposta.text.lower()
    assert situacao_do_mes(sessao, creche, date(2026, 8, 1)).ligadas == 6  # o extrato entrou antes
    tela = cliente.get(f"/empresas/{creche.id}?aba=extratos&mes=2026-08").text
    assert "Demonstrativos" in tela and "LOJA SEM EXTRATO" in tela and "FULANO DESCONHECIDO" in tela
