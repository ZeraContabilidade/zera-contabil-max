"""Classificação dos movimentos do extrato: nomes cortados e abreviados pelo banco, CNPJ, valor recorrente,
regras de banco, transferência entre contas da própria empresa e o que o usuário escolheu (nunca refeito)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.leitores import ExtratoLido, MovimentoLido, ler_extrato
from app.modelos import ContaChave, ContaContabil, Empresa, MovimentoExtrato
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.classificacao import classificar, semelhanca
from app.servicos.extratos import importar_extrato
from tests.conftest import DADOS, entrar
from tests.planos import criar_plano

# ---------------------------------------------------------------- nomes (sem banco)


@pytest.mark.parametrize(
    ("banco", "aprendido", "minimo"),
    [
        ("MARIANA A R COSTA", "MARIANA APARECIDA RIBEIRO COSTA", 100),  # iniciais soltas
        ("FERNANDO DE SOUSA PEREIR", "FERNANDO SOUSA PEREIRA", 100),  # cortado pelo banco
        ("EMPRESA EXEMPLO SERVICOS E", "EMPRESA EXEMPLO SERV CONTABEIS", 100),  # abreviado no histórico
        ("ALFA SUPRIMENTOS LTDA", "ALFA SUMPRIMENTOS", 100),  # erro de digitação no histórico
        ("COMPANHIA DE AGUA EXEMPL", "COMPANHIA DE AGUA EXEMPLO", 100),
        ("SANEAMENTO", "SANEAMENTO", 100),
    ],
)
def test_nomes_parecidos(banco, aprendido, minimo):
    assert semelhanca(banco, aprendido) >= minimo


@pytest.mark.parametrize(
    ("banco", "aprendido"),
    [
        ("JOSE SILVA", "MARIA SILVA"),  # primeiro nome diferente
        ("SANTOS", "MARIA DOS SANTOS"),  # uma palavra curta não identifica
        ("MERCADO CENTRAL", "PAPELARIA CENTRAL"),
    ],
)
def test_nomes_diferentes(banco, aprendido):
    assert semelhanca(banco, aprendido) < 75


# ---------------------------------------------------------------- classificação (com banco)


def mov(dia, valor, sentido, historico, complemento="", mes=8):
    return MovimentoLido(date(2026, mes, dia), Decimal(valor), sentido, historico, complemento)


CONTA_CORRENTE = [
    mov(3, "98.10", "SAIDA", "Pagamento de Boleto", "COMPANHIA DE AGUA EXEMPL"),  # nome cortado → 355
    mov(5, "910.00", "SAIDA", "Pagamento de Boleto", "INTERMEDIADORA DE PAGAMENTO"),  # valor do sindicato → 10594
    mov(6, "2861.25", "SAIDA", "Transferência enviada", "MARIA SOUZA"),  # salário → 187
    mov(7, "12.50", "SAIDA", "Tarifa Pacote de Serviços"),  # conta-chave TARIFA
    mov(8, "500.00", "SAIDA", "Aplicação Poupança", "ASSOCIACAO EXEMPLO"),  # para a poupança
    mov(9, "77.00", "SAIDA", "Pix - Enviado", "FULANO DESCONHECIDO"),  # ninguém conhece
    mov(10, "346.50", "SAIDA", "Pix - Enviado", "11.222.333 SINDICATO EXE"),  # raiz do CNPJ
]
POUPANCA = [
    mov(8, "500.00", "ENTRADA", "Transferência de Crédito", "ASSOCIACAO EXEMPLO"),  # a outra ponta
    mov(31, "3.21", "ENTRADA", "Juros"),
    mov(31, "0.48", "SAIDA", "Imposto De Renda"),
]


def extrato(tipo, movimentos) -> ExtratoLido:
    return ExtratoLido(
        leitor="teste",
        banco="Banco do Brasil",
        agencia="1234-5",
        numero="12345-6",
        tipo=tipo,
        titular="ASSOCIACAO EXEMPLO",
        inicio=date(2026, 8, 1),
        fim=date(2026, 8, 31),
        movimentos=movimentos,
    )


@pytest.fixture
def empresa(sessao, criar_usuario, cliente, monkeypatch):
    criar_usuario("ana")
    entrar(cliente, "ana")
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    criar_plano(sessao, nova)
    importar_historico(sessao, nova, "lanctos.txt", (DADOS / "lanctos_exemplo.txt").read_bytes(), None)
    aprender(sessao, nova)
    for tipo, reduzido in (("TARIFA", 535), ("RENDIMENTO", 10107), ("IR_RETIDO", 31)):
        conta = sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == reduzido))
        sessao.add(ContaChave(empresa_id=nova.id, tipo=tipo, referencia="", conta_id=conta.id, origem="REGRA",
                              confianca=95))  # fmt: skip
    sessao.commit()
    lidos = {"cc.pdf": extrato("BANCO", CONTA_CORRENTE), "poupanca.pdf": extrato("POUPANCA", POUPANCA)}
    monkeypatch.setattr(
        "app.servicos.extratos.ler_extrato", lambda nome, conteudo: lidos.get(nome) or ler_extrato(nome, conteudo)
    )
    return nova


def sugestoes(sessao) -> dict[tuple[str, str], tuple]:
    """(histórico, valor) → (status, origem, débito, crédito, confiança)."""
    resultado = {}
    for m in sessao.scalars(select(MovimentoExtrato)):
        s = m.sugestao
        debito = s.conta_debito.reduzido if s.conta_debito else None
        credito = s.conta_credito.reduzido if s.conta_credito else None
        chave = (m.complemento or m.historico, f"{m.valor}")
        if chave in resultado:  # as duas pontas da transferência têm o mesmo texto e valor
            chave = (chave[0], f"{m.valor}/{m.sentido}")
        resultado[chave] = (s.status, s.origem, debito, credito, s.confianca)
    return resultado


@pytest.mark.banco
def test_classifica_pelo_que_aprendeu_e_pelas_regras(empresa, sessao):
    importar_extrato(sessao, empresa, "cc.pdf", b"%PDF-falso", None)
    importar_extrato(sessao, empresa, "poupanca.pdf", b"%PDF-falso", None)
    sessao.commit()
    feito = sugestoes(sessao)
    assert feito[("COMPANHIA DE AGUA EXEMPL", "98.10")][:4] == ("APROVADO", "NOME", 355, 8)
    assert feito[("MARIA SOUZA", "2861.25")][:4] == ("APROVADO", "NOME", 187, 8)
    assert feito[("INTERMEDIADORA DE PAGAMENTO", "910.00")][:4] == ("PENDENTE", "VALOR", 10594, 8)  # amarela
    assert feito[("Tarifa Pacote de Serviços", "12.50")][:4] == ("APROVADO", "REGRA", 535, 8)
    assert feito[("11.222.333 SINDICATO EXE", "346.50")][:2] == ("APROVADO", "CNPJ")
    assert feito[("FULANO DESCONHECIDO", "77.00")][:2] == ("PENDENTE", "PENDENTE")
    # transferência para a poupança: lançada uma vez, na saída (D poupança 11 / C banco 8); a entrada sem lançamento
    transferencias = sorted(v[:4] for k, v in feito.items() if k[0] == "ASSOCIACAO EXEMPLO")
    assert transferencias == [("APROVADO", "TRANSFERENCIA", 11, 8), ("IGNORADO", "TRANSFERENCIA", None, None)]
    assert feito[("Juros", "3.21")][:4] == ("APROVADO", "REGRA", 11, 10107)
    assert feito[("Imposto De Renda", "0.48")][:4] == ("APROVADO", "REGRA", 31, 11)

    complemento = sessao.scalar(
        select(MovimentoExtrato).where(MovimentoExtrato.complemento == "COMPANHIA DE AGUA EXEMPL")
    ).sugestao.complemento
    assert complemento.startswith("COMPANHIA DE AGUA EXEMPLO - 44.555.666/0001-81 - CONTA DE AGUA")


@pytest.mark.banco
def test_transferencia_sem_o_outro_extrato_e_sem_conta_da_poupanca(empresa, sessao):
    importar_extrato(sessao, empresa, "cc.pdf", b"%PDF-falso", None)
    sozinha = sugestoes(sessao)[("ASSOCIACAO EXEMPLO", "500.00")]
    assert sozinha[:2] == ("PENDENTE", "TRANSFERENCIA")  # o extrato da poupança ainda não chegou

    poupanca = sessao.scalar(select(ContaChave).where(ContaChave.tipo == "POUPANCA"))
    importar_extrato(sessao, empresa, "poupanca.pdf", b"%PDF-falso", None)
    poupanca = sessao.scalar(select(ContaChave).where(ContaChave.tipo == "POUPANCA"))
    poupanca.conta_id = None  # a poupança sem conta contábil (como na Casa Criança)
    classificar(sessao, empresa, date(2026, 8, 1), date(2026, 8, 31))
    pares = [v for k, v in sugestoes(sessao).items() if k[0] == "ASSOCIACAO EXEMPLO"]
    assert all(v[:2] == ("PENDENTE", "TRANSFERENCIA") for v in pares)
    movimento = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.historico == "Aplicação Poupança"))
    assert "não tem conta contábil" in movimento.sugestao.justificativa

    poupanca.conta_id = sessao.scalar(select(ContaContabil.id).where(ContaContabil.reduzido == 8))  # mesma conta
    classificar(sessao, empresa, date(2026, 8, 1), date(2026, 8, 31))
    pares = [v for k, v in sugestoes(sessao).items() if k[0] == "ASSOCIACAO EXEMPLO"]
    assert [v[0] for v in pares] == ["IGNORADO", "IGNORADO"]  # cai na mesma conta: não gera lançamento


@pytest.mark.banco
def test_o_que_o_usuario_escolheu_nao_e_refeito(empresa, sessao):
    importar_extrato(sessao, empresa, "cc.pdf", b"%PDF-falso", None)
    movimento = sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.complemento == "FULANO DESCONHECIDO"))
    material = sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == 359))
    movimento.sugestao.conta_debito, movimento.sugestao.origem = material, "USUARIO"
    movimento.sugestao.status = "APROVADO"
    sessao.commit()
    classificar(sessao, empresa, date(2026, 8, 1), date(2026, 8, 31))
    sessao.refresh(movimento.sugestao)
    assert (movimento.sugestao.origem, movimento.sugestao.conta_debito.reduzido) == ("USUARIO", 359)


@pytest.mark.banco
def test_aba_extratos_mostra_as_sugestoes_e_classifica_de_novo(cliente, empresa, sessao):
    cliente.post(
        f"/empresas/{empresa.id}/extratos", files=[("arquivos", ("cc.pdf", b"%PDF-falso"))], follow_redirects=True
    )
    tela = cliente.get(f"/empresas/{empresa.id}", params={"aba": "extratos", "mes": "2026-08"}).text
    assert "Lançamento sugerido" in tela and "aprovado(s)" in tela and "pelo nome" in tela
    tela = cliente.post(f"/empresas/{empresa.id}/extratos/classificar", data={"mes": "2026-08"}, follow_redirects=True)
    assert "Classificação:" in tela.text


@pytest.mark.banco
@pytest.mark.amostras
def test_casa_crianca_real_agosto(sessao):
    """Histórico real aprendido + extratos reais de agosto: quanto o sistema resolve sozinho (sem IA)."""
    from app.servicos.contas_chave import auto_configurar
    from app.servicos.plano import importar_plano, ler_plano
    from tests.conftest import AMOSTRAS

    arquivos = [
        AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv",
        AMOSTRAS / "historicos" / "lanctos_2025_casa_crianca.txt",
        AMOSTRAS / "PLANILHA EXPORTAÇÃO" / "modelo exemplar da exportacao.txt",
        AMOSTRAS / "EXTRATOS" / "EXTRATO CONTA CORRENTE.pdf",
    ]
    if not all(a.exists() for a in arquivos):
        pytest.skip("AMOSTRAS/ não está neste computador")
    plano, lanctos_2025, lanctos_2026, corrente = arquivos
    empresa = Empresa(codigo_dominio=230)
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(plano.read_bytes(), plano.name), None)
    auto_configurar(sessao, empresa)
    for arquivo in (lanctos_2025, lanctos_2026):
        importar_historico(sessao, empresa, arquivo.name, arquivo.read_bytes(), None)
    aprender(sessao, empresa)
    extrato_cc = importar_extrato(sessao, empresa, corrente.name, corrente.read_bytes(), None)
    sessao.commit()
    print("\n" + extrato_cc.importacao.resumo["classificacao"])

    feito = sugestoes(sessao)
    salarios = [v for k, v in feito.items() if v[1] == "NOME" and v[2] == 187]
    assert len(salarios) >= 14  # os salários de 28/08 (nomes cortados e abreviados pelo banco)
    assert feito[("SABESP", "600.35")][:3] == ("APROVADO", "NOME", 355)
    assert feito[("ZERA ASSESSORIA EMPRESARIAL E", "1200.00")][:3] == ("APROVADO", "NOME", 10571)
    assert feito[("LYTEX INSTITUICAO DE PAGAMENTO", "910.00")][1:3] == ("VALOR", 10594)  # plano odontológico
    fora_transferencias = [v for v in feito.values() if v[1] != "TRANSFERENCIA"]
    resolvidos = [v for v in fora_transferencias if v[0] == "APROVADO" or v[4] >= 70]
    assert len(resolvidos) >= 0.8 * len(fora_transferencias)
