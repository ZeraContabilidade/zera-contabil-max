"""Servidor de teste: mostra as telas com dados de exemplo, sem tocar nos dados reais.

Usa o banco <nome>_teste, apaga o que houver nele, cria usuários de exemplo
e sobe o sistema em http://127.0.0.1:8001 (o sistema real continua na 8000).
Uso: .venv\\Scripts\\python -m scripts.servidor_teste
"""

import uvicorn

from scripts.banco_teste import criar_banco_teste, esvaziar_tabelas, usar_banco_teste
from scripts.comum import ErroAmigavel, rodar

PORTA = 8001
SENHA_EXEMPLO = "senha-de-teste-123"  # só existe no banco de teste
USUARIOS_EXEMPLO = [
    ("ana", "Ana Supervisora", "SUPERVISOR"),
    ("carla", "Carla Assistente", "ASSISTENTE"),
    ("davi", "Davi Contador", "CONTADOR"),
]


def main() -> int:
    url = usar_banco_teste()
    if not criar_banco_teste(url):
        raise ErroAmigavel("O PostgreSQL está desligado. Rode o INICIAR.bat uma vez para ligar o banco.")

    from app.auth import gerar_hash
    from app.db import aplicar_migracoes, fabrica_sessoes
    from app.modelos import Empresa, Papel, Regime, Usuario

    aplicar_migracoes()
    esvaziar_tabelas()
    with fabrica_sessoes()() as sessao:
        usuarios = {}
        for login, nome, papel in USUARIOS_EXEMPLO:
            usuarios[login] = Usuario(
                nome=nome, login=login, senha_hash=gerar_hash(SENHA_EXEMPLO), papel=Papel(papel)
            )
            sessao.add(usuarios[login])
        sessao.flush()
        # empresas fictícias (nunca dados reais de clientes no código)
        sessao.add_all(
            [
                Empresa(
                    codigo_dominio=900,
                    razao_social="ASSOCIACAO CRECHE EXEMPLO",
                    nome_curto="Creche Exemplo",
                    cnpj_cpf="12ABC34501DE35",
                    regime=Regime.TERCEIRO_SETOR,
                    responsavel_id=usuarios["carla"].id,
                    campos_automaticos=["razao_social", "regime"],
                    dados_publicos={
                        "natureza_juridica": "3999 - Associação Privada",
                        "atividade": "Educação infantil - creche",
                        "municipio": "SÃO PAULO/SP",
                        "situacao": "ATIVA",
                        "consultado_em": "2026-10-06",
                    },
                ),
                Empresa(codigo_dominio=901, razao_social="PADARIA PÃO MODELO LTDA", regime=Regime.SIMPLES),
                Empresa(codigo_dominio=902, nome_curto="Mercado Teste", ativa=False),
            ]
        )
        sessao.commit()

    print(f"Servidor de TESTE em http://127.0.0.1:{PORTA} (usuários: ana, carla, davi)")
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORTA, log_level="warning")
    return 0


if __name__ == "__main__":
    rodar(main)
