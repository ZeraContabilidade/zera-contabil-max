"""Tela de Revisão: conferir, corrigir, aprovar, ignorar, reabrir — e cada decisão ensina o mês seguinte."""

from datetime import date

import pytest
from sqlalchemy import select

from app.leitores import ExtratoLido, ler_extrato
from app.modelos import (
    ContaChave,
    ContaContabil,
    Empresa,
    Importacao,
    LancamentoHistorico,
    Log,
    MovimentoExtrato,
    Padrao,
    Sugestao,
)
from app.servicos.aprendizado import aprender, importar_historico
from app.servicos.classificacao import classificar
from app.servicos.classificacao_ia import candidatas
from app.servicos.extratos import importar_extrato
from app.servicos.progresso import progresso_do_mes
from tests.conftest import DADOS, entrar
from tests.planos import criar_plano
from tests.test_classificacao import CONTA_CORRENTE, extrato, mov

HTMX = {"HX-Request": "true"}
AGOSTO = date(2026, 8, 1)
DUAS_VEZES = [  # o mesmo favorecido duas vezes no mês, ninguém conhece
    mov(20, "45.00", "SAIDA", "Pix - Enviado", "MERCEARIA ZETA"),
    mov(27, "52.00", "SAIDA", "Pix - Enviado", "MERCEARIA ZETA"),
]
SETEMBRO = ExtratoLido(
    leitor="teste",
    banco="Banco do Brasil",
    agencia="1234-5",
    numero="12345-6",
    tipo="BANCO",
    titular="ASSOCIACAO EXEMPLO",
    inicio=date(2026, 9, 1),
    fim=date(2026, 9, 30),
    movimentos=[mov(4, "81.00", "SAIDA", "Pix - Enviado", "FULANO DESCONHECIDO", mes=9)],
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
    tarifa = sessao.scalar(select(ContaContabil).where(ContaContabil.reduzido == 535))
    sessao.add(ContaChave(empresa_id=nova.id, tipo="TARIFA", referencia="", conta_id=tarifa.id, origem="REGRA"))
    sessao.commit()
    lidos = {"cc.pdf": extrato("BANCO", CONTA_CORRENTE + DUAS_VEZES), "setembro.pdf": SETEMBRO}
    monkeypatch.setattr(
        "app.servicos.extratos.ler_extrato", lambda nome, conteudo: lidos.get(nome) or ler_extrato(nome, conteudo)
    )
    importar_extrato(sessao, nova, "cc.pdf", b"%PDF-falso", None)
    sessao.commit()
    return nova


def sugestao_de(sessao, texto: str, mes: int = 8, vez: int = 0) -> Sugestao:
    movimentos = sessao.scalars(
        select(MovimentoExtrato)
        .where(MovimentoExtrato.complemento == texto, MovimentoExtrato.data >= date(2026, mes, 1))
        .order_by(MovimentoExtrato.data)
    ).all()
    return movimentos[vez].sugestao


def recarregar(sessao, sugestao: Sugestao) -> Sugestao:
    sessao.expire_all()
    return sessao.get(Sugestao, sugestao.id)


def reduzidos(sugestao: Sugestao) -> tuple:
    debito = sugestao.conta_debito.reduzido if sugestao.conta_debito else None
    credito = sugestao.conta_credito.reduzido if sugestao.conta_credito else None
    return sugestao.status, sugestao.origem, debito, credito


def lancamento_da_revisao(sessao, favorecido: str) -> LancamentoHistorico | None:
    return sessao.scalar(select(LancamentoHistorico).where(LancamentoHistorico.favorecido == favorecido))


def ensinados_pela_revisao(sessao) -> int:
    revisao = select(Importacao.id).where(Importacao.tipo == "REVISAO")
    return len(sessao.scalars(select(LancamentoHistorico).where(LancamentoHistorico.importacao_id.in_(revisao))).all())


@pytest.mark.banco
def test_aba_mostra_o_que_precisa_de_atencao_e_filtra(cliente, empresa):
    tela = cliente.get(f"/empresas/{empresa.id}", params={"aba": "revisao", "mes": "2026-08"}).text
    assert "FULANO DESCONHECIDO" in tela and "INTERMEDIADORA DE PAGAMENTO" in tela  # pendente e amarela
    assert "COMPANHIA DE AGUA EXEMPL" not in tela  # já aprovada: fora de “Precisa de atenção”
    assert 'value="355 – ÁGUA E ESGOTO" label="355 – AGUA E ESGOTO"' in tela  # “agua” acha a conta
    todos = cliente.get(f"/empresas/{empresa.id}", params={"aba": "revisao", "filtro": "todos"}).text
    assert "COMPANHIA DE AGUA EXEMPL" in todos
    busca = cliente.get(f"/empresas/{empresa.id}", params={"aba": "revisao", "filtro": "todos", "q": "companhia"})
    assert "COMPANHIA DE AGUA EXEMPL" in busca.text and "FULANO DESCONHECIDO" not in busca.text
    conta = cliente.get(f"/empresas/{empresa.id}", params={"aba": "revisao", "filtro": "todos", "conta": "355"})
    assert "COMPANHIA DE AGUA EXEMPL" in conta.text and "MERCEARIA ZETA" not in conta.text


@pytest.mark.banco
def test_corrigir_a_conta_aprova_e_ensina_o_mes_seguinte(cliente, empresa, sessao):
    sugestao = sugestao_de(sessao, "FULANO DESCONHECIDO")
    resposta = cliente.post(
        f"/empresas/{empresa.id}/revisao/{sugestao.id}",
        data={"acao": "salvar", "conta": "359 – MATERIAL DE ESCRITÓRIO", "complemento": "FULANO - MATERIAL"},
        headers=HTMX,
    )
    assert resposta.status_code == 200 and resposta.text.lstrip().startswith("<tr")  # só a linha volta
    assert "escolhido à mão" in resposta.text
    sugestao = recarregar(sessao, sugestao)
    assert reduzidos(sugestao) == ("APROVADO", "USUARIO", 359, 8)
    assert sugestao.complemento == "FULANO - MATERIAL" and sugestao.conferido_por_id is not None
    # virou lançamento do histórico e padrão aprendido
    assert lancamento_da_revisao(sessao, "FULANO DESCONHECIDO").contrapartida.reduzido == 359
    padrao = sessao.scalar(select(Padrao).where(Padrao.nome.ilike("%fulano%")))
    assert padrao.conta.reduzido == 359
    log = sessao.scalar(select(Log).where(Log.entidade == "sugestao", Log.entidade_id == str(sugestao.id)))
    assert log.acao == "ALTERAR" and log.usuario.login == "ana"  # quem mudou fica no log

    classificar(sessao, empresa, AGOSTO, date(2026, 8, 31))  # classificar de novo não desfaz
    assert reduzidos(recarregar(sessao, sugestao)) == ("APROVADO", "USUARIO", 359, 8)

    importar_extrato(sessao, empresa, "setembro.pdf", b"%PDF-falso", None)  # mês seguinte: sai sozinha
    sessao.commit()
    assert reduzidos(sugestao_de(sessao, "FULANO DESCONHECIDO", mes=9)) == ("APROVADO", "NOME", 359, 8)


@pytest.mark.banco
def test_conta_errada_mostra_o_erro_na_propria_linha(cliente, empresa, sessao):
    sugestao = sugestao_de(sessao, "FULANO DESCONHECIDO")
    url = f"/empresas/{empresa.id}/revisao/{sugestao.id}"
    resposta = cliente.post(url, data={"acao": "salvar", "conta": "99999"}, headers=HTMX)
    assert "A conta 99999 não existe no plano desta empresa." in resposta.text
    resposta = cliente.post(url, data={"acao": "aprovar"}, headers=HTMX)
    assert "Escolha a conta antes de aprovar." in resposta.text
    assert recarregar(sessao, sugestao).status == "PENDENTE"


@pytest.mark.banco
def test_conta_pelo_nome_sem_escolher_na_lista(cliente, empresa, sessao):
    sugestao = sugestao_de(sessao, "FULANO DESCONHECIDO")
    url = f"/empresas/{empresa.id}/revisao/{sugestao.id}"
    resposta = cliente.post(url, data={"acao": "salvar", "conta": "material", "complemento": "X"}, headers=HTMX)
    assert "Mais de uma conta tem “material” no nome: 359 – MATERIAL DE ESCRITÓRIO, 360 – " in resposta.text
    assert 'value="material"' in resposta.text  # a linha volta com o que foi digitado
    cliente.post(url, data={"acao": "salvar", "conta": "agua"}, headers=HTMX)  # sem acento, uma conta só
    assert reduzidos(recarregar(sessao, sugestao)) == ("APROVADO", "USUARIO", 355, 8)


@pytest.mark.banco
def test_aplicar_as_linhas_parecidas(cliente, empresa, sessao):
    primeira, segunda = sugestao_de(sessao, "MERCEARIA ZETA"), sugestao_de(sessao, "MERCEARIA ZETA", vez=1)
    resposta = cliente.post(
        f"/empresas/{empresa.id}/revisao/{primeira.id}", data={"acao": "salvar", "conta": "359"}, headers=HTMX
    )
    assert "Aplicar às 1" in resposta.text  # oferece a outra linha do mesmo favorecido
    resposta = cliente.post(f"/empresas/{empresa.id}/revisao/{primeira.id}/parecidas", headers=HTMX)
    assert resposta.headers["HX-Redirect"].endswith("aba=revisao&mes=2026-08")
    assert reduzidos(recarregar(sessao, segunda)) == ("APROVADO", "USUARIO", 359, 8)


@pytest.mark.banco
def test_aprovar_ignorar_e_reabrir(cliente, empresa, sessao, ia_falsa):
    amarela = sugestao_de(sessao, "INTERMEDIADORA DE PAGAMENTO")
    url = f"/empresas/{empresa.id}/revisao/{amarela.id}"
    assert (
        cliente.post(url, data={"acao": "aprovar"}, follow_redirects=False).status_code == 303
    )  # sem HTMX: volta para a aba
    amarela = recarregar(sessao, amarela)
    assert reduzidos(amarela) == ("APROVADO", "VALOR", 10594, 8) and amarela.conferido_por_id
    assert ensinados_pela_revisao(sessao) == 1  # a aprovação conta como mais um lançamento no histórico
    cliente.post(url, data={"acao": "reabrir"})
    amarela = recarregar(sessao, amarela)
    assert (amarela.status, amarela.conferido_por_id) == ("PENDENTE", None)
    assert ensinados_pela_revisao(sessao) == 0  # reabrir desfaz o que tinha ensinado

    pendente = sugestao_de(sessao, "FULANO DESCONHECIDO")
    cliente.post(f"/empresas/{empresa.id}/revisao/{pendente.id}", data={"acao": "ignorar"}, headers=HTMX)
    pendente = recarregar(sessao, pendente)
    assert pendente.status == "IGNORADO"
    classificar(sessao, empresa, AGOSTO, date(2026, 8, 31))
    assert recarregar(sessao, pendente).status == "IGNORADO"  # a classificação não mexe no conferido
    movimentos = sessao.scalars(select(MovimentoExtrato)).all()
    assert pendente not in candidatas(sessao, empresa, movimentos)  # nem a IA


@pytest.mark.banco
def test_revisao_concluida_na_barra_do_mes(cliente, empresa, sessao):
    def etapa_revisao():
        return next(e for e in progresso_do_mes(sessao, empresa, AGOSTO) if e.chave == "revisao")

    assert etapa_revisao().situacao == "atual"
    for sugestao in sessao.scalars(select(Sugestao).where(Sugestao.status == "PENDENTE")).all():
        cliente.post(f"/empresas/{empresa.id}/revisao/{sugestao.id}", data={"acao": "salvar", "conta": "359"})
    sessao.expire_all()
    assert etapa_revisao().situacao == "feita"


@pytest.mark.banco
def test_linha_exportada_ou_de_outra_empresa_nao_muda(cliente, empresa, sessao):
    sugestao = sugestao_de(sessao, "FULANO DESCONHECIDO")
    sugestao.status = "EXPORTADO"
    sessao.commit()
    resposta = cliente.post(
        f"/empresas/{empresa.id}/revisao/{sugestao.id}", data={"acao": "salvar", "conta": "359"}, follow_redirects=True
    )
    assert "Esta linha não pode mais ser mudada" in resposta.text
    assert recarregar(sessao, sugestao).conta_debito is None
    resposta = cliente.post(f"/empresas/{empresa.id}/revisao/999999", data={"acao": "ignorar"}, follow_redirects=True)
    assert "Esta linha não pode mais ser mudada" in resposta.text


@pytest.mark.banco
def test_varias_linhas_de_uma_vez(cliente, empresa, sessao, monkeypatch):
    fulano = sugestao_de(sessao, "FULANO DESCONHECIDO")
    zeta1, zeta2 = sugestao_de(sessao, "MERCEARIA ZETA"), sugestao_de(sessao, "MERCEARIA ZETA", vez=1)
    amarela = sugestao_de(sessao, "INTERMEDIADORA DE PAGAMENTO")
    lote = f"/empresas/{empresa.id}/revisao/lote"
    volta = {"mes": "2026-08", "filtro": "todos", "q": "", "conta_filtro": ""}

    resposta = cliente.post(lote, data={**volta, "acao": "aprovar"}, follow_redirects=True)
    assert "Marque as linhas" in resposta.text

    resposta = cliente.post(
        lote, data={**volta, "acao": "aprovar", "ids": [amarela.id, fulano.id]}, follow_redirects=True
    )
    assert "Aprovada(s) 1 linha(s)." in resposta.text and "1 linha(s) sem conta não foram aprovadas" in resposta.text
    assert recarregar(sessao, amarela).status == "APROVADO"

    vezes = []
    import app.servicos.revisao as revisao

    original = revisao.aprender
    monkeypatch.setattr(revisao, "aprender", lambda *a, **k: vezes.append(1) or original(*a, **k))
    ids = [fulano.id, zeta1.id, zeta2.id]
    resposta = cliente.post(lote, data={**volta, "acao": "conta", "conta": "escrit", "ids": ids}, follow_redirects=True)
    assert "359 – MATERIAL DE ESCRITÓRIO aplicada a 3 linha(s)." in resposta.text
    assert "filtro=todos" in str(resposta.url)  # volta para o mesmo filtro
    assert [reduzidos(recarregar(sessao, s)) for s in (fulano, zeta1, zeta2)] == [("APROVADO", "USUARIO", 359, 8)] * 3
    assert vezes == [1]  # aprendeu uma vez só, no fim
    assert ensinados_pela_revisao(sessao) == 4  # a amarela aprovada + as 3 corrigidas

    cliente.post(lote, data={**volta, "acao": "ignorar", "ids": [zeta2.id]})
    assert recarregar(sessao, zeta2).status == "IGNORADO" and ensinados_pela_revisao(sessao) == 3


@pytest.mark.banco
def test_aprovacao_automatica_configuravel_por_empresa(cliente, empresa, sessao):
    def tarifa():
        sessao.expire_all()
        return sessao.scalar(select(MovimentoExtrato).where(MovimentoExtrato.historico == "Tarifa Pacote de Serviços"))

    assert (tarifa().sugestao.status, tarifa().sugestao.confianca) == ("PENDENTE", 80)  # padrão: só a partir de 90
    dados = {"codigo_dominio": "230", "nome_curto": "Creche Teste", "modelo_complemento": empresa.modelo_complemento}
    resposta = cliente.post(f"/empresas/{empresa.id}", data={**dados, "limiar_aprovacao": "65"})
    assert resposta.status_code == 400 and "A aprovação automática vai de 70% a 100% (padrão 90%)" in resposta.text
    salvo = cliente.post(f"/empresas/{empresa.id}", data={**dados, "limiar_aprovacao": "80"}, follow_redirects=False)
    assert salvo.status_code == 303
    sessao.refresh(empresa)
    assert empresa.limiar_aprovacao == 80
    classificar(sessao, empresa, AGOSTO, date(2026, 8, 31))
    sessao.commit()
    assert tarifa().sugestao.status == "APROVADO"
    cliente.post(f"/empresas/{empresa.id}", data={**dados, "limiar_aprovacao": ""})  # em branco volta ao padrão
    sessao.refresh(empresa)
    assert empresa.limiar_aprovacao == 90
