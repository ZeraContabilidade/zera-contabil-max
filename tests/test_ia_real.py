"""Teste com a API REAL da Anthropic. Custa uma fração de centavo e só roda quando pedido:

    .venv\\Scripts\\python -m pytest -m ia_real -s

Usa a chave e os modelos do arquivo .env; sem chave, o teste é pulado.
"""

from dataclasses import replace

import pytest
from dotenv import dotenv_values

from app.config import RAIZ, Config
from app.ia.cliente import ClienteAnthropic
from app.ia.servico import PEDIDO_TESTE

pytestmark = pytest.mark.ia_real

_ENV = dotenv_values(RAIZ / ".env") if (RAIZ / ".env").exists() else {}
_PADRAO = Config(_env_file=None)
MODELOS = [
    _ENV.get("IA_MODELO_RAPIDO") or _PADRAO.ia_modelo_rapido,
    _ENV.get("IA_MODELO_FORTE") or _PADRAO.ia_modelo_forte,
]


@pytest.fixture(scope="module")
def cliente_real():
    chave = (_ENV.get("ANTHROPIC_API_KEY") or "").strip()
    if not chave:
        pytest.skip("Sem ANTHROPIC_API_KEY no arquivo .env")
    return ClienteAnthropic(chave, _PADRAO.ia_endereco)


@pytest.mark.banco
@pytest.mark.amostras
def test_auto_configuracao_real_casa_crianca(cliente_real, sessao, monkeypatch):
    """A IA de verdade escolhe as contas incertas do plano real (≈ US$ 0,05). Mostra o resultado."""
    from app.modelos import Empresa
    from app.servicos.contas_chave import auto_configurar
    from app.servicos.plano import importar_plano, ler_plano
    from tests.conftest import AMOSTRAS

    arquivo = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    if not arquivo.exists():
        pytest.skip("AMOSTRAS/ não está neste computador")
    monkeypatch.setattr("app.ia.servico.obter_cliente", lambda: cliente_real)
    empresa = Empresa(codigo_dominio=230, nome_curto="Casa Criança")
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(arquivo.read_bytes(), arquivo.name), None)
    sessao.commit()

    resultado = auto_configurar(sessao, empresa)
    assert resultado.ia_usada, resultado.aviso_ia
    for chave in resultado.chaves:
        conta = chave.conta.rotulo if chave.conta else "—"
        print(f"\n{chave.tipo:<20} {conta:<45} {chave.origem:<5} {chave.confianca:>3}% {chave.justificativa}")
        if chave.conta:
            assert chave.conta.analitica  # conferência: só analíticas que existem


@pytest.mark.parametrize("modelo", MODELOS)
def test_modelos_respondem_json_no_formato_pedido(cliente_real, modelo):
    # o modelo forte pensa antes de responder: precisa de mais espaço
    pedido = PEDIDO_TESTE if "haiku" in modelo else replace(PEDIDO_TESTE, max_tokens=4000, esforco="low")
    resposta = cliente_real.gerar(pedido, modelo)
    assert resposta.dados["ok"] is True
    assert resposta.dados["mensagem"]
    assert resposta.uso.entrada > 0 and resposta.uso.saida > 0
    print(f"\n{modelo} → {resposta.modelo}: {resposta.dados['mensagem']!r} | {resposta.uso}")


@pytest.mark.banco
@pytest.mark.amostras
def test_ia_real_no_diario_da_casa_crianca(cliente_real, sessao, monkeypatch):
    """A IA de verdade revisa o que as regras não separaram no Diário real (≈ US$ 0,02). Mostra as decisões."""
    from sqlalchemy import select

    from app.modelos import ContaChave, Empresa, LancamentoHistorico
    from app.servicos.aprendizado import aprender, importar_historico
    from app.servicos.historico_ia import agrupar, revisar_historico
    from app.servicos.plano import importar_plano, ler_plano
    from tests.conftest import AMOSTRAS

    plano = AMOSTRAS / "PLANO DE CONTAS" / "contas crianca.csv"
    diario = AMOSTRAS / "historicos" / "Diário.xls"
    lanctos = AMOSTRAS / "PLANILHA EXPORTAÇÃO" / "modelo exemplar da exportacao.txt"
    if not all(a.exists() for a in (plano, diario, lanctos)):
        pytest.skip("AMOSTRAS/ não está neste computador")
    monkeypatch.setattr("app.ia.servico.obter_cliente", lambda: cliente_real)
    empresa = Empresa(codigo_dominio=230, nome_curto="Casa Criança")
    sessao.add(empresa)
    sessao.commit()
    importar_plano(sessao, empresa, ler_plano(plano.read_bytes(), plano.name), None)
    for arquivo in (lanctos, diario):
        importar_historico(sessao, empresa, arquivo.name, arquivo.read_bytes(), None)
    sessao.commit()
    pendentes = agrupar(list(sessao.scalars(select(LancamentoHistorico).where(~LancamentoHistorico.revisado_ia))))

    revisao = revisar_historico(sessao, empresa)
    resultado = aprender(sessao, empresa)
    sessao.commit()
    print("\n" + revisao.resumo().replace("🤖 ", "") + " " + revisao.aviso)
    for grupo in pendentes:
        exemplo = grupo.exemplo
        if not exemplo.revisado_ia:
            continue
        conta = exemplo.contrapartida.reduzido if exemplo.contrapartida else "-"
        print(
            f"{len(grupo.lancamentos):>3}x {exemplo.sentido:<7} {conta:>6} "
            f"{exemplo.historico[:55]:<55} → {exemplo.favorecido or '-'} | {exemplo.natureza or '-'}"
        )
    print(resultado.resumo().replace("🤖 ", ""))
    rendimento = sessao.scalar(select(ContaChave).where(ContaChave.tipo == "RENDIMENTO"))
    print(f"RENDIMENTO → {rendimento.conta.rotulo if rendimento else '-'}")
    assert revisao.revisados > 0 and not revisao.aviso
    repasse = sessao.scalar(select(LancamentoHistorico).where(LancamentoHistorico.historico == "REPASSE MUNICIPAL"))
    aquisicao = sessao.scalar(select(LancamentoHistorico).where(LancamentoHistorico.historico.like("AQUISICAO%")))
    assert repasse.sentido == "ENTRADA" and aquisicao.sentido == "OUTRO"


@pytest.mark.banco
@pytest.mark.amostras
def test_ia_real_le_o_pdf_do_bb_como_banco_desconhecido(cliente_real, sessao, monkeypatch):
    """O PDF real da conta corrente do BB pelo leitor universal (≈ US$ 0,10): tem que dar o mesmo que o
    leitor próprio — 49 movimentos, entradas = saídas = 149.568,52."""
    from decimal import Decimal

    from app.leitores.universal_ia import ler_pdf_com_ia
    from app.modelos import Empresa
    from tests.conftest import AMOSTRAS

    pdf = AMOSTRAS / "EXTRATOS" / "EXTRATO CONTA CORRENTE.pdf"
    if not pdf.exists():
        pytest.skip("AMOSTRAS/ não está neste computador")
    monkeypatch.setattr("app.ia.servico.obter_cliente", lambda: cliente_real)
    empresa = Empresa(codigo_dominio=230, nome_curto="Casa Criança")
    sessao.add(empresa)
    sessao.commit()

    lido = ler_pdf_com_ia(sessao, empresa, None, pdf.name, pdf.read_bytes())
    entradas = sum(m.valor for m in lido.movimentos if m.sentido == "ENTRADA")
    saidas = sum(m.valor for m in lido.movimentos if m.sentido == "SAIDA")
    print(f"\n{lido.banco} | ag {lido.agencia} | conta {lido.numero} | {lido.inicio} a {lido.fim} | "
          f"saldo {lido.saldo_inicial} → {lido.saldo_final} | {len(lido.movimentos)} movimentos | "
          f"entradas {entradas} | saídas {saidas}")  # fmt: skip
    for m in lido.movimentos[:6]:
        print(f"  {m.data} {m.sentido:<7} {m.valor:>10} {m.historico} | {m.complemento}")
    for aviso in lido.avisos:
        print("  aviso:", aviso.texto)
    assert len(lido.movimentos) == 49
    assert entradas == saidas == Decimal("149568.52")
    assert "72637" in lido.numero
