"""Pasta de entrada: os extratos novos da pasta do cliente entram sozinhos (só leitura, sem repetir, sem IA)."""

import os

import pytest
from sqlalchemy import func, select

from app.leitores import NaoReconhecido, ler_extrato
from app.modelos import Extrato, MovimentoExtrato
from app.servicos.pasta_entrada import PastaInvalida, buscar_na_pasta
from tests.test_ofx import empresa, montar_ofx  # noqa: F401 — empresa com o plano de teste (BB 12345-6 = conta 8)

pytestmark = pytest.mark.banco
SETEMBRO_OFX = [("20260904", "-81.00", "Pix - Enviado - 04/09 10:00 FULANO DESCONHECIDO", "90401")]


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    """Como a do escritório: subpastas dos meses, cópia repetida “(1)”, .rar, PDF de banco sem leitor próprio, o PDF do
    BB igual ao OFX do mesmo mês e uma planilha que não é extrato."""
    raiz = tmp_path / "EXTRATOS 2026"
    agosto, setembro = raiz / "8. AGOSTO", raiz / "9. SETEMBRO"
    agosto.mkdir(parents=True)
    setembro.mkdir()
    (agosto / "Extrato123456.ofx").write_bytes(montar_ofx())
    (agosto / "Extrato123456 (1).ofx").write_bytes(montar_ofx())  # a mesma coisa baixada duas vezes
    (agosto / "12345-6-CC-AGO.pdf").write_bytes(b"%PDF-1.4 banco sem leitor")
    (agosto / "Downloads.rar").write_bytes(b"Rar!")
    ofx_setembro = montar_ofx(SETEMBRO_OFX, saldo="519.00", inicio="20260901", fim="20260930")
    (setembro / "Extrato123456.ofx").write_bytes(ofx_setembro)
    (setembro / "12345-6-CC-SET.pdf").write_bytes(b"%PDF-1.4 o mesmo extrato em PDF")
    (raiz / "PLANILHA ANUAL").mkdir()
    (raiz / "PLANILHA ANUAL" / "controle.xlsx").write_bytes(b"PK planilha do escritorio")

    def ler(nome, conteudo):
        if nome == "12345-6-CC-SET.pdf":  # o leitor do BB lê: os mesmos movimentos do OFX de setembro
            return ler_extrato("igual.ofx", ofx_setembro)
        if nome.endswith(".pdf"):
            raise NaoReconhecido("PDF de banco sem leitor próprio")
        return ler_extrato(nome, conteudo)

    monkeypatch.setattr("app.servicos.extratos.ler_extrato", ler)
    monkeypatch.setattr("app.servicos.extratos.ler_pdf_com_ia", lambda *a, **k: pytest.fail("a busca não usa IA"))
    return raiz


def contar(sessao, modelo) -> int:
    return sessao.scalar(select(func.count()).select_from(modelo))


def test_busca_le_o_que_e_novo_e_pula_o_resto(cliente, empresa, sessao, pasta):  # noqa: F811
    empresa.pasta_extratos = str(pasta)
    sessao.commit()
    tela = cliente.post(f"/empresas/{empresa.id}/extratos/pasta", follow_redirects=True).text
    # a cópia “(1)” e o PDF igual ao OFX contam como “já estavam”; o PDF igual não vira mais um extrato na lista
    assert "Pasta do cliente: 2 extrato(s) lido(s) com 4 movimento(s) novo(s), 2 já estavam no sistema." in tela
    assert "12345-6-CC-AGO.pdf" in tela and "sem leitor próprio não foram lidos" in tela
    assert "controle.xlsx" in tela and "não foram lidas sozinhas" in tela
    assert "Downloads.rar" not in tela
    assert (contar(sessao, Extrato), contar(sessao, MovimentoExtrato)) == (2, 4)
    assert "2 arquivo(s) da pasta que o sistema não lê sozinho" in tela  # o PDF sem leitor e a planilha

    de_novo = cliente.post(f"/empresas/{empresa.id}/extratos/pasta", follow_redirects=True).text
    assert "nenhum extrato novo (6 arquivo(s) já estavam no sistema)" in de_novo  # nem abre o que não mudou
    assert "sem leitor próprio não foram lidos" not in de_novo  # o aviso não se repete
    assert contar(sessao, Extrato) == 2

    mais_um = [*SETEMBRO_OFX, ("20260920", "-45.00", "Pix - Enviado - 20/09 10:00 MERCEARIA ZETA", "92001")]
    (pasta / "9. SETEMBRO" / "Extrato123456.ofx").write_bytes(  # baixado de novo, agora com mais um movimento
        montar_ofx(mais_um, saldo="474.00", inicio="20260901", fim="20260930")
    )
    os.utime(pasta / "9. SETEMBRO" / "Extrato123456.ofx", (2_000_000_000, 2_000_000_000))
    terceira = cliente.post(f"/empresas/{empresa.id}/extratos/pasta", follow_redirects=True).text
    assert "1 extrato(s) lido(s) com 1 movimento(s) novo(s)" in terceira
    assert contar(sessao, MovimentoExtrato) == 5


def test_pasta_que_nao_existe_ou_vazia(cliente, empresa, sessao, tmp_path):  # noqa: F811
    with pytest.raises(PastaInvalida, match="Informe no Cadastro"):
        buscar_na_pasta(sessao, empresa, None)
    empresa.pasta_extratos = str(tmp_path / "nao existe")
    sessao.commit()
    tela = cliente.post(f"/empresas/{empresa.id}/extratos/pasta", follow_redirects=True).text
    assert "Não encontrei a pasta" in tela and "Cadastro da empresa" in tela


def test_cadastro_guarda_a_pasta_sem_aspas_e_mostra_o_botao(cliente, empresa, sessao, tmp_path):  # noqa: F811
    dados = {"codigo_dominio": "230", "nome_curto": "Creche Teste", "ativa": "on",
             "modelo_complemento": empresa.modelo_complemento, "pasta_extratos": f'"{tmp_path}"'}  # fmt: skip
    cliente.post(f"/empresas/{empresa.id}", data=dados)
    sessao.refresh(empresa)
    assert empresa.pasta_extratos == str(tmp_path)
    tela = cliente.get(f"/empresas/{empresa.id}", params={"aba": "extratos"}).text
    assert "Buscar extratos novos" in tela and str(tmp_path) in tela
