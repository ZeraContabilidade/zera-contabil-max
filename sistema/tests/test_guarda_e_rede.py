"""Guarda dos arquivos por 5 anos (§7.3) e acesso pela rede do escritório (§7.1).
Os testes de rede nunca mexem no Firewall de verdade: o netsh é simulado."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.modelos import ArquivoOriginal, Empresa, Log
from app.servicos.armazenamento import (
    ArquivoApagado,
    apagar_vencidos,
    guardar_arquivo,
    ler_arquivo,
    obter_armazenamento,
)
from scripts import rede
from scripts.comum import ErroAmigavel

# ---------------------------------------------------------------- guarda de 5 anos


@pytest.fixture
def empresa(sessao):
    nova = Empresa(codigo_dominio=230, nome_curto="Creche Teste")
    sessao.add(nova)
    sessao.commit()
    return nova


def _existe(arquivo: ArquivoOriginal) -> bool:
    try:
        obter_armazenamento().ler(arquivo.chave)
    except FileNotFoundError:
        return False
    return True


@pytest.mark.banco
def test_apaga_o_que_passou_de_5_anos_e_guarda_o_registro(empresa, sessao):
    antigo = guardar_arquivo(sessao, empresa, "EXTRATO", "extrato 2021.pdf", b"extrato antigo", None)
    novo = guardar_arquivo(sessao, empresa, "EXTRATO", "extrato 2026.pdf", b"extrato novo", None)
    assert novo.expira_em.year == date.today().year + 5
    # o mesmo conteúdo enviado de novo depois: um registro venceu, o outro não — o arquivo fica no disco
    repetido_velho = guardar_arquivo(sessao, empresa, "PLANO", "plano.txt", b"plano igual", None)
    repetido_novo = guardar_arquivo(sessao, empresa, "PLANO", "plano de novo.txt", b"plano igual", None)
    ontem = date.today() - timedelta(days=1)
    antigo.expira_em = repetido_velho.expira_em = ontem
    sessao.commit()

    resultado = apagar_vencidos(sessao)
    sessao.commit()
    assert {a.nome_original for a in resultado.apagados} == {"extrato 2021.pdf", "plano.txt"}
    assert antigo.excluido_em is not None and not _existe(antigo)  # o arquivo saiu do disco…
    assert sessao.get(ArquivoOriginal, antigo.id).sha256  # …e o registro ficou
    assert _existe(novo) and repetido_velho.excluido_em is not None and _existe(repetido_novo)
    assert resultado.bytes_liberados == len(b"extrato antigo")
    log = sessao.scalar(select(Log).where(Log.acao == "APAGAR_ARQUIVOS_VENCIDOS"))
    assert log.detalhe.startswith("2 arquivo(s) com mais de 5 anos apagado(s)")

    with pytest.raises(ArquivoApagado, match="foi apagado em .* \\(guarda de 5 anos\\)"):
        ler_arquivo(antigo)
    assert ler_arquivo(novo) == b"extrato novo"
    assert apagar_vencidos(sessao).apagados == []  # nada mais a apagar (e nenhum evento novo)


@pytest.mark.banco
def test_o_iniciar_faz_a_guarda_sozinho(empresa, sessao):
    from scripts.iniciar import guarda_dos_arquivos

    vencido = guardar_arquivo(sessao, empresa, "EXTRATO", "velho.pdf", b"velho", None)
    vencido.expira_em = date.today() - timedelta(days=1)
    sessao.commit()
    guarda_dos_arquivos()
    sessao.expire_all()
    assert sessao.get(ArquivoOriginal, vencido.id).excluido_em is not None


# ---------------------------------------------------------------- acesso pela rede


def test_troca_so_a_linha_host_do_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=segredo\nHOST=127.0.0.1\nPORTA=8000\n", encoding="utf-8")
    rede.trocar_host(env, rede.REDE_DO_ESCRITORIO)
    assert env.read_text(encoding="utf-8") == "POSTGRES_PASSWORD=segredo\nHOST=0.0.0.0\nPORTA=8000\n"
    sem_host = tmp_path / "sem_host.env"
    sem_host.write_text("PORTA=8000", encoding="utf-8")
    rede.trocar_host(sem_host, rede.SO_ESTE_COMPUTADOR)
    assert sem_host.read_text(encoding="utf-8") == "PORTA=8000\nHOST=127.0.0.1\n"


def test_regra_do_firewall_so_para_rede_privada():
    comando = rede.comando_liberar(8000)
    assert "profile=private" in comando and "localport=8000" in comando and "dir=in" in comando
    assert rede.comando_fechar()[-1] == "name=ZERA CONTABIL MAX"


def test_enderecos_da_rede_sem_o_proprio_computador(monkeypatch):
    infos = [(2, 1, 6, "", ("192.168.0.10", 0)), (2, 1, 6, "", ("127.0.0.1", 0)), (2, 1, 6, "", ("192.168.0.10", 0))]
    monkeypatch.setattr(rede.socket, "getaddrinfo", lambda *a, **k: infos)
    assert rede.enderecos_da_rede() == ["192.168.0.10"]


@pytest.fixture
def raiz_falsa(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HOST=127.0.0.1\n", encoding="utf-8")
    monkeypatch.setattr(rede, "ARQUIVO_ENV", tmp_path / ".env")
    comandos = []
    monkeypatch.setattr(rede, "_netsh", lambda comando: comandos.append(comando) or True)
    monkeypatch.setattr(rede, "enderecos_da_rede", lambda: ["192.168.0.10"])
    return tmp_path, comandos


def test_liberar_exige_administrador(raiz_falsa, monkeypatch):
    monkeypatch.setattr(rede, "_administrador", lambda: False)
    with pytest.raises(ErroAmigavel, match="Executar como administrador"):
        rede.main(["liberar"])
    assert raiz_falsa[1] == []  # nada foi mexido


def test_liberar_e_fechar(raiz_falsa, monkeypatch, capsys):
    raiz, comandos = raiz_falsa
    monkeypatch.setattr(rede, "_administrador", lambda: True)
    assert rede.main(["liberar"]) == 0
    assert "HOST=0.0.0.0" in (raiz / ".env").read_text(encoding="utf-8")
    assert [c[3] for c in comandos] == ["delete", "add"]  # não duplica a regra
    assert "http://192.168.0.10:" in capsys.readouterr().out
    assert rede.main(["fechar"]) == 0
    assert "HOST=127.0.0.1" in (raiz / ".env").read_text(encoding="utf-8")
    assert comandos[-1][3] == "delete"
