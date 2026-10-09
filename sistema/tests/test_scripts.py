import pytest

from app.config import RAIZ
from scripts import configurar_ia, instalar
from scripts.comum import ErroAmigavel, rodar
from scripts.criar_env import MARCADOR, criar_env


def test_criar_env_gera_senhas_diferentes_e_tira_o_marcador(tmp_path):
    modelo = tmp_path / ".env.example"
    modelo.write_text(f"# comentário\nSENHA={MARCADOR}\nCHAVE={MARCADOR}\nPORTA=8000\n", encoding="utf-8")
    destino = tmp_path / ".env"

    assert criar_env(modelo, destino) is True

    valores = dict(
        linha.split("=", 1)
        for linha in destino.read_text(encoding="utf-8").splitlines()
        if "=" in linha and not linha.startswith("#")
    )
    assert MARCADOR not in destino.read_text(encoding="utf-8")
    assert len(valores["SENHA"]) >= 24
    assert valores["SENHA"] != valores["CHAVE"]
    assert valores["PORTA"] == "8000"


def test_criar_env_nunca_sobrescreve_um_env_existente(tmp_path):
    modelo = tmp_path / ".env.example"
    modelo.write_text(f"SENHA={MARCADOR}\n", encoding="utf-8")
    destino = tmp_path / ".env"
    destino.write_text("SENHA=antiga\n", encoding="utf-8")

    assert criar_env(modelo, destino) is False
    assert destino.read_text(encoding="utf-8") == "SENHA=antiga\n"


def test_completar_env_acrescenta_so_o_que_falta_com_os_comentarios(tmp_path):
    from scripts.criar_env import completar_env

    modelo = tmp_path / ".env.example"
    modelo.write_text(
        f"SENHA={MARCADOR}\nPORTA=8000\n\n# --- IA ---\n# cole a chave aqui\nANTHROPIC_API_KEY=\nIA_LIMITE=20\n",
        encoding="utf-8",
    )
    destino = tmp_path / ".env"
    destino.write_text("SENHA=minha-senha\nPORTA=9000\n", encoding="utf-8")

    assert completar_env(modelo, destino) == ["ANTHROPIC_API_KEY", "IA_LIMITE"]
    texto = destino.read_text(encoding="utf-8")
    assert texto.startswith("SENHA=minha-senha\nPORTA=9000\n")  # o que existia não muda
    assert "# cole a chave aqui\nANTHROPIC_API_KEY=\nIA_LIMITE=20\n" in texto
    assert completar_env(modelo, destino) == []  # rodar de novo não duplica


def test_erro_amigavel_vira_mensagem_e_codigo_1(capsys):
    def falha() -> int:
        raise ErroAmigavel("Abra o Docker Desktop e tente de novo.")

    with pytest.raises(SystemExit) as saida:
        rodar(falha)
    assert saida.value.code == 1
    assert "[ERRO] Abra o Docker Desktop e tente de novo." in capsys.readouterr().out


CHAVE_FALSA = "sk-ant-" + "x" * 30  # só o formato de uma chave, não é uma chave de verdade


def test_configurar_ia_troca_so_a_linha_da_chave():
    env = "# comentário\nANTHROPIC_API_KEY=\nPORTA=8000\n"
    esperado = f"# comentário\nANTHROPIC_API_KEY={CHAVE_FALSA}\nPORTA=8000\n"
    assert configurar_ia.gravar_chave(env, CHAVE_FALSA) == esperado
    assert configurar_ia.gravar_chave("PORTA=8000", CHAVE_FALSA) == f"PORTA=8000\nANTHROPIC_API_KEY={CHAVE_FALSA}\n"


def test_configurar_ia_recusa_o_que_nao_parece_chave(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(configurar_ia, "ARQUIVO_ENV", env)
    monkeypatch.setattr(configurar_ia.getpass, "getpass", lambda _: "minha senha")
    with pytest.raises(ErroAmigavel, match="sk-ant-"):
        configurar_ia.main()
    assert env.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=\n"  # nada mudou


def test_configurar_ia_guarda_a_chave_sem_mostrar_e_apagar_desliga(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(configurar_ia, "ARQUIVO_ENV", env)
    monkeypatch.setattr(configurar_ia.getpass, "getpass", lambda _: f"  {CHAVE_FALSA}\n")  # colada com espaços
    assert configurar_ia.main() == 0
    assert env.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={CHAVE_FALSA}\n"
    assert CHAVE_FALSA not in capsys.readouterr().out  # a chave nunca aparece na tela
    monkeypatch.setattr(configurar_ia.getpass, "getpass", lambda _: "apagar")
    assert configurar_ia.main() == 0
    assert env.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=\n"


def test_instalar_esconde_so_as_pastas_tecnicas(tmp_path, monkeypatch):
    for nome in (".venv", ".git", "dados", "Ferramentas"):
        (tmp_path / nome).mkdir()
    monkeypatch.setattr(instalar, "RAIZ", tmp_path)
    monkeypatch.setattr(instalar.sys, "platform", "win32")
    comandos = []
    monkeypatch.setattr(instalar.subprocess, "run", lambda comando, **_: comandos.append(comando))
    assert instalar.ocultar_pastas_tecnicas() == [".git", ".venv"]
    assert comandos == [["attrib", "+h", str(tmp_path / ".git")], ["attrib", "+h", str(tmp_path / ".venv")]]


def test_pasta_principal_organizada():
    """O que o usuário vê na pasta do sistema: só o INICIAR.bat solto; o resto nas pastas certas."""
    ferramentas = RAIZ / "Ferramentas"
    for nome in ("INSTALAR.bat", "ATUALIZAR.bat", "RESTAURAR_BACKUP.bat", "LIBERAR_REDE.bat", "FECHAR_REDE.bat",
                 "CONFIGURAR_IA.bat", "Preparar computador/PREPARAR_COMPUTADOR.bat"):  # fmt: skip
        assert (ferramentas / nome).is_file(), nome
    assert sorted(p.name for p in RAIZ.glob("*.bat")) == ["INICIAR.bat"]
    assert len(list((RAIZ / "Manuais").glob("*.md"))) == 4
    for bat in [RAIZ / "INICIAR.bat", *ferramentas.rglob("*.bat")]:
        conteudo = bat.read_bytes()
        assert conteudo.isascii(), f"{bat.name}: no .bat, só letras sem acento"
        assert conteudo.count(b"\n") == conteudo.count(b"\r\n"), f"{bat.name}: quebra de linha do Windows (CRLF)"
