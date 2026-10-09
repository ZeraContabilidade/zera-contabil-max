"""Parte Python do INICIAR.bat: liga o banco, sobe o sistema, abre o navegador, faz o backup do dia e apaga os
arquivos que passaram dos 5 anos de guarda."""

import argparse
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from app.config import ARQUIVO_ENV, obter_config
from scripts.banco_docker import preparar_banco
from scripts.comum import ErroAmigavel, rodar
from scripts.rede import REDE_DO_ESCRITORIO, enderecos_da_rede


def sistema_respondendo(url: str) -> bool:
    # tempo curto: no Windows uma porta fechada só dá "recusado" depois de ~2 s
    try:
        with urllib.request.urlopen(f"{url}/saude", timeout=0.5) as resposta:
            return resposta.status == 200
    except OSError:
        return False


def abrir_navegador_quando_pronto(url_interna: str, url: str, espera_segundos: int = 60) -> None:
    limite = time.monotonic() + espera_segundos
    while time.monotonic() < limite:
        if sistema_respondendo(url_interna):
            webbrowser.open(url)
            return
        time.sleep(1)


def guarda_dos_arquivos() -> None:
    """Apaga os arquivos que passaram dos 5 anos (§7.3); o registro e o evento no log ficam."""
    from app.db import fabrica_sessoes
    from app.servicos.armazenamento import apagar_vencidos

    with fabrica_sessoes()() as sessao:
        resultado = apagar_vencidos(sessao)
        sessao.commit()
    if resultado.apagados:
        print(resultado.resumo())


def backup_automatico(parar: threading.Event, checar_a_cada_segundos: int = 30 * 60) -> None:
    """Um backup por dia: ao abrir o sistema e, se ele ficar aberto, a cada 24 horas. Antes, a guarda de 5 anos."""
    from app.servicos import backup

    while True:
        try:
            guarda_dos_arquivos()
        except Exception as erro:  # noqa: BLE001 — a guarda nunca pode derrubar o backup
            print(f"\n[ATENÇÃO] Não foi possível apagar os arquivos com mais de 5 anos: {erro}\n")
        try:
            if backup.situacao().precisa_backup():
                print(backup.fazer_backup("automatico").resumo())
        except backup.ErroBackup as erro:
            print(f"\n[ATENÇÃO] O backup automático não foi feito: {erro}\n")
            backup.registrar_falha(erro)
        except Exception as erro:  # noqa: BLE001 — a rotina nunca pode morrer calada: o backup de amanhã depende dela
            print(f"\n[ATENÇÃO] O backup automático falhou: {erro}\n")
            backup.registrar_falha(erro)
        if parar.wait(checar_a_cada_segundos):
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inicia o ZERA CONTÁBIL MAX")
    parser.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    args = parser.parse_args(argv)

    if not ARQUIVO_ENV.exists():
        raise ErroAmigavel(
            "O sistema ainda não foi instalado. Abra a pasta Ferramentas e dê dois cliques no INSTALAR.bat."
        )

    config = obter_config()
    # verificação por 127.0.0.1: no Windows "localhost" tenta IPv6 antes e demora ~2 s por tentativa
    url_interna = f"http://127.0.0.1:{config.porta}"
    url = f"http://localhost:{config.porta}"
    if sistema_respondendo(url_interna):
        print("O sistema já está aberto em outra janela. Abrindo o navegador...")
        if not args.sem_navegador:
            webbrowser.open(url)
        return 0

    preparar_banco()
    threading.Thread(target=backup_automatico, args=(threading.Event(),), daemon=True).start()
    if not args.sem_navegador:
        threading.Thread(target=abrir_navegador_quando_pronto, args=(url_interna, url), daemon=True).start()
    print(f"\nSistema no ar em {url}")
    if config.host == REDE_DO_ESCRITORIO:
        for endereco in enderecos_da_rede():
            print(f"Nos outros computadores do escritório: http://{endereco}:{config.porta}")
    print("Para desligar o sistema, feche esta janela.\n")
    uvicorn.run("app.main:app", host=config.host, port=config.porta, log_level="warning")
    return 0


if __name__ == "__main__":
    rodar(main)
