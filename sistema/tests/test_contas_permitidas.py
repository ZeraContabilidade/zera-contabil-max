"""Contas que o sistema pode sugerir (15/10/2026): cada creche só as suas (plano com contas de várias creches, como
o da associação 121) e associação (terceiro setor) lança na despesa, nunca na conta do fornecedor."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.leitores import ExtratoLido, MovimentoLido
from app.modelos import ContaContabil, Empresa, Regime
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.classificacao import classificar
from app.servicos.contas_permitidas import (
    FiltroContas,
    carregar_filtro,
    contas_de_fornecedor,
    unidade_da_empresa,
    unidades_do_plano,
)
from app.servicos.empresas import ler_formulario
from app.servicos.extratos import importar_extrato
from tests.conftest import entrar
from tests.planos import criar_plano

# plano de associação com contas de várias creches (dados fictícios no formato do plano real)
PLANO_CRECHES = [
    (1, "1", "ATIVO", "S"),
    (2, "11", "ATIVO CIRCULANTE", "S"),
    (7, "11102", "BANCOS CONTA MOVIMENTO", "S"),
    (8, "11102000001", "BCO BRASIL CC 12345-6", "A"),
    (100, "2", "PASSIVO", "S"),
    (101, "21", "PASSIVO CIRCULANTE", "S"),
    (164, "213", "FORNECEDORES", "S"),
    (10571, "21301000001", "PADARIA BOM PÃO", "A"),  # no grupo de fornecedores
    (7066, "21900000001", "ADONAI DISTRIBUIDORA LTDA.", "A"),  # sem grupo, mas com nome de empresa
    (185, "215", "OBRIGAÇÕES TRABALHISTAS", "S"),
    (187, "21501000001", "SALÁRIOS A PAGAR", "A"),
    (191, "21502000001", "INSS A RECOLHER LTDA", "A"),  # obrigação, nunca fornecedor
    (300, "4", "CONTAS DE RESULTADO - DESPESAS", "S"),
    (301, "41", "DESPESAS OPERACIONAIS", "S"),
    (7007, "41000000001", "SALÁRIO MENSAL - CARMEM DIAS", "A"),
    (7044, "41000000002", "SALÁRIO MENSAL - JANDIRA", "A"),
    (7027, "41000000003", "SALÁRIO MENSAL - PASTOR MARIO", "A"),
    (7011, "41000000004", "ÁGUA E ESGOTO - CARMEM DIAS", "A"),
    (7053, "41000000005", "ÁGUA E ESGOTO - JANDIRA", "A"),
    (7017, "41000000006", "ENERGIA ELETRICA - CARMEM DIAS", "A"),
    (7049, "41000000007", "ENERGIA ELÉTRICA - JANDIRA", "A"),
    (7020, "41000000008", "ALIMENTAÇÃO DO TRABALHADOR", "A"),  # comum
    (7052, "41000000009", "ALIMENTAÇÃO DO TRABALHADOR - JANDIRA", "A"),
    (7029, "41000000010", "ALIMENTAÇÃO DO TRABALHADOR - PASTOR MARI", "A"),  # cortada em 40 letras
    (7056, "41000000011", "MATERIAL PEDAGOGICO - JANDIRA", "A"),  # a Carmem Dias não tem
    (7013, "41000000012", "CESTA BÁSICA - CARMEM DIAS", "A"),
    (7028, "41000000013", "CESTA BÁSICA - PASTOR MARIO", "A"),
    (360, "41000000014", "MATERIAL DE LIMPEZA", "A"),
    (5000, "41000000015", "INSS - EMPRESA", "A"),  # “EMPRESA” não é creche
    (5001, "41000000016", "FGTS - EMPRESA", "A"),
    (5002, "41000000017", "PIS - EMPRESA", "A"),
]


def _contas() -> list[ContaContabil]:
    contas = []
    for n, (reduzido, classificacao, descricao, tipo) in enumerate(PLANO_CRECHES, 1):
        partes = [classificacao[0], classificacao[1:2], classificacao[2:3], classificacao[3:5], classificacao[5:]]
        formatada = ".".join(p for p in partes if p)
        contas.append(
            ContaContabil(
                id=n,
                empresa_id=1,
                reduzido=reduzido,
                classificacao=classificacao,
                classificacao_formatada=formatada,
                descricao=descricao,
                tipo=tipo,
                nivel=len([p for p in partes if p]),
                ativa=True,
            )
        )
    return contas


def _filtro(unidade="CARMEM DIAS", regime=None) -> tuple[FiltroContas, dict[int, ContaContabil]]:
    contas = _contas()
    empresa = Empresa(codigo_dominio=121, nome_curto="Creche", unidade=unidade, regime=regime)
    unidades = unidades_do_plano(contas)
    filtro = FiltroContas(empresa, {c.id: c for c in contas}, unidades, unidade_da_empresa(empresa, unidades))
    return filtro, {c.reduzido: c for c in contas}


def test_acha_as_creches_do_plano_mesmo_com_o_nome_cortado():
    assert unidades_do_plano(_contas()) == ["CARMEM DIAS", "JANDIRA", "PASTOR MARIO"]


def test_a_mesma_creche_escrita_de_jeitos_diferentes():
    contas = _contas()
    nomes = ["SALÁRIO MENSAL - PARAVATI", "ÁGUA E ESGOTO - ROGERIO", "CESTA BÁSICA - ROGERIO PARAVATI"]
    for n, descricao in enumerate(nomes):
        contas.append(ContaContabil(id=900 + n, reduzido=900 + n, classificacao=f"41000000{90 + n}",
                                    classificacao_formatada=f"4.1.0.00.0000{90 + n}", descricao=descricao, tipo="A",
                                    nivel=5, ativa=True))  # fmt: skip
    assert unidades_do_plano(contas) == ["CARMEM DIAS", "JANDIRA", "PASTOR MARIO", "ROGERIO PARAVATI"]


def test_unidade_vem_do_cadastro_ou_da_conta_do_banco():
    unidades = ["CARMEM DIAS", "JANDIRA", "ROGERIO PARAVATI"]
    assert unidade_da_empresa(Empresa(unidade="Rogério Paravati"), unidades) == "ROGERIO PARAVATI"
    assert unidade_da_empresa(Empresa(unidade="paravati"), unidades) == "ROGERIO PARAVATI"
    assert unidade_da_empresa(Empresa(nome_curto="Creche Jandira"), unidades) == ""  # pelo nome, não
    filtro, por_reduzido = _filtro(unidade=None)
    banco = ContaContabil(id=999, reduzido=999, descricao="BANCO DO BRASIL 12345-6 - JANDIRA", tipo="A")
    assert filtro.unidade_para(banco) == "JANDIRA"
    assert filtro.ajustar(por_reduzido[7011], banco)[0].reduzido == 7053  # ÁGUA da Carmem → a da Jandira
    assert filtro.ajustar(por_reduzido[7011])[0].reduzido == 7011  # banco sem unidade: nada muda


@pytest.mark.parametrize(
    ("de", "para"),
    [
        (7053, 7011),  # ÁGUA E ESGOTO - JANDIRA → a da Carmem Dias
        (7049, 7017),  # ENERGIA ELÉTRICA (com acento) → ENERGIA ELETRICA
        (7052, 7020),  # a Carmem Dias usa a conta comum
        (7029, 7020),  # “PASTOR MARI” cortado também é de outra creche
        (7007, 7007),  # a dela fica
        (5000, 5000),  # “INSS - EMPRESA” é conta comum
        (360, 360),
    ],
)
def test_conta_de_outra_creche_vira_a_mesma_conta_desta(de, para):
    filtro, por_reduzido = _filtro()
    conta, nota = filtro.ajustar(por_reduzido[de])
    assert conta.reduzido == para
    assert bool(nota) == (de != para)


def test_conta_que_a_creche_nao_tem_fica_pendente():
    filtro, por_reduzido = _filtro()
    conta, nota = filtro.ajustar(por_reduzido[7056])
    assert conta is None
    assert "JANDIRA" in nota and "CARMEM DIAS" in nota


def test_sem_unidade_nada_muda():
    filtro, por_reduzido = _filtro(unidade=None)
    assert filtro.ajustar(por_reduzido[7053])[0].reduzido == 7053


def test_contas_de_fornecedor_pelo_grupo_ou_pelo_nome_de_empresa():
    contas = _contas()
    achadas = {c.reduzido for c in contas if c.id in contas_de_fornecedor(contas, Empresa(codigo_dominio=1))}
    assert achadas == {10571, 7066}


def test_associacao_troca_o_fornecedor_pela_despesa_aprendida():
    filtro, por_reduzido = _filtro(unidade=None, regime=Regime.TERCEIRO_SETOR)
    filtro.de_fornecedor = {por_reduzido[10571].id, por_reduzido[7066].id}
    filtro.despesa_do_fornecedor = {por_reduzido[10571].id: por_reduzido[360].id}
    conta, nota = filtro.ajustar(por_reduzido[10571])
    assert conta.reduzido == 360 and "despesa" in nota
    conta, nota = filtro.ajustar(por_reduzido[7066])  # sem histórico: escolher a despesa
    assert conta is None and "despesa" in nota


# ---------------------------------------------------------------- na classificação (com banco)

HISTORICO = "\r\n".join(
    [
        # provisão (débito na despesa, crédito no fornecedor) e pagamento (débito no fornecedor) — prática antiga
        "05/06/2026;360;10571;150,00;;PADARIA BOM PAO - LANCHE - 55;1;121;;",
        "10/06/2026;10571;8;150,00;;PADARIA BOM PAO - LANCHE - 55;1;121;;",
        "05/07/2026;360;10571;180,00;;PADARIA BOM PAO - LANCHE - 61;1;121;;",
        "10/07/2026;10571;8;180,00;;PADARIA BOM PAO - LANCHE - 61;1;121;;",
        # a SABESP aprendida na conta da Jandira
        "12/07/2026;7053;8;300,00;;SABESP - AGUA - S/N;1;121;;",
        "12/06/2026;7053;8;280,00;;SABESP - AGUA - S/N;1;121;;",
    ]
).encode("cp1252")


def _extrato() -> ExtratoLido:
    def mov(dia, valor, historico, complemento):
        return MovimentoLido(date(2026, 8, dia), Decimal(valor), "SAIDA", historico, complemento)

    return ExtratoLido(
        leitor="teste",
        banco="Banco do Brasil",
        agencia="1234-5",
        numero="12345-6",
        tipo="BANCO",
        titular="ASSOCIACAO EXEMPLO",
        inicio=date(2026, 8, 1),
        fim=date(2026, 8, 31),
        movimentos=[
            mov(10, "190.00", "Pix - Enviado", "PADARIA BOM PAO"),
            mov(12, "310.00", "Pagamento de Boleto", "SABESP"),
        ],
    )


@pytest.fixture
def creche(sessao, criar_usuario, cliente, monkeypatch):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=121, nome_curto="Creche Carmem", unidade="Carmem Dias")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova, PLANO_CRECHES)
    importar_historico(sessao, nova, "lanctos.txt", HISTORICO, None)
    aprender(sessao, nova)
    sessao.commit()
    monkeypatch.setattr("app.servicos.extratos.ler_extrato", lambda nome, conteudo: _extrato())
    return nova


def _contrapartidas(sessao, empresa) -> dict[str, int | None]:
    from app.modelos import MovimentoExtrato

    resultado = {}
    for m in sessao.scalars(select(MovimentoExtrato).where(MovimentoExtrato.empresa_id == empresa.id)):
        conta = m.sugestao.conta_debito
        resultado[m.complemento] = conta.reduzido if conta else None
    return resultado


@pytest.mark.banco
def test_classificacao_usa_a_conta_da_creche_e_a_despesa_da_associacao(sessao, creche):
    creche.regime = Regime.TERCEIRO_SETOR
    sessao.commit()
    importar_extrato(sessao, creche, "cc.pdf", b"%PDF-", None)
    sessao.commit()
    assert _contrapartidas(sessao, creche) == {"PADARIA BOM PAO": 360, "SABESP": 7011}
    filtro = carregar_filtro(sessao, creche)
    assert filtro.unidade == "CARMEM DIAS"


@pytest.mark.banco
def test_empresa_comum_continua_na_conta_do_fornecedor(sessao, creche):
    creche.regime = Regime.SIMPLES
    creche.unidade = None
    sessao.commit()
    importar_extrato(sessao, creche, "cc.pdf", b"%PDF-", None)
    sessao.commit()
    assert _contrapartidas(sessao, creche) == {"PADARIA BOM PAO": 10571, "SABESP": 7053}
    classificar(sessao, creche, date(2026, 8, 1), date(2026, 8, 31))


@pytest.mark.banco
def test_creches_com_o_mesmo_codigo_e_cnpj_sao_cadastros_diferentes(sessao):
    sessao.add(Empresa(codigo_dominio=121, nome_curto="Associação (sede)"))
    form = {"codigo_dominio": "121", "cnpj_cpf": "03.532.026/0001-79", "unidade": "Carmem Dias"}
    valores, erros = ler_formulario(sessao, form)
    assert not erros
    sessao.add(Empresa(**valores))
    sessao.commit()
    _, erros = ler_formulario(sessao, {**form, "unidade": "JANDIRA"})
    assert not erros
    _, erros = ler_formulario(sessao, {**form, "unidade": "carmem dias"})  # mesma creche
    assert any("já é o cadastro" in e for e in erros)
    _, erros = ler_formulario(sessao, {"codigo_dominio": "121", "unidade": ""})
    assert any("preencha a unidade" in e for e in erros)


@pytest.mark.banco
def test_conta_do_banco_da_creche_vem_do_historico_dela(sessao, creche):
    from app.modelos import ContaBancaria, ContaChave
    from app.servicos.contas_permitidas import ligar_contas_da_unidade

    linhas = [f"{dia:02d}/07/2026;7011;8;100,00;;SABESP - AGUA - S/N;1;121;;" for dia in range(1, 7)]
    importar_historico(sessao, creche, "carmem.txt", "\r\n".join(linhas).encode("cp1252"), None)
    chave = ContaChave(empresa_id=creche.id, tipo="POUPANCA", referencia="BB conta 55555-5", origem="IA", confianca=60)
    sessao.add(chave)
    sessao.flush()
    sessao.add(ContaBancaria(empresa_id=creche.id, banco_codigo="001", banco_nome="Banco do Brasil", agencia="1234-5",
                             numero="55555-5", tipo="POUPANCA", conta_chave_id=chave.id))  # fmt: skip
    sessao.commit()
    assert ligar_contas_da_unidade(sessao, creche) == 1
    assert chave.conta.reduzido == 8 and "CARMEM DIAS" in chave.justificativa
    chave.origem = "USUARIO"  # a escolha do usuário nunca é trocada
    chave.conta_id = None
    assert ligar_contas_da_unidade(sessao, creche) == 0
