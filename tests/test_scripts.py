import pytest

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
        f"SENHA={MARCADOR}\nPORTA=8000\n\n# --- IA ---\n"
        "# cole a chave aqui\nANTHROPIC_API_KEY=\nIA_LIMITE=20\n",
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
