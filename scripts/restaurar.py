"""Parte Python do RESTAURAR.bat: troca os dados do sistema pelos de um backup.

Uso: RESTAURAR.bat               → mostra os backups e pergunta qual
     RESTAURAR.bat <arquivo.dump> → restaura esse arquivo (ex.: copiado de outro computador)
"""

import argparse
from pathlib import Path

from app.config import RAIZ, obter_config
from app.servicos import backup
from scripts.comum import ErroAmigavel, rodar
from scripts.iniciar import sistema_respondendo

CONFIRMACAO = "RESTAURAR"


def backups_disponiveis() -> list[tuple[backup.Backup, str]]:
    """Backups do computador e do Google Drive (sem repetir), do mais recente para o mais antigo."""
    alvos = backup.destinos()
    vistos: dict[str, tuple[backup.Backup, str]] = {}
    for pasta, onde in ((alvos.local, "computador"), (alvos.nuvem, "Google Drive")):
        for item in backup.listar_backups(pasta):
            vistos.setdefault(item.nome, (item, onde))  # o do computador abre mais rápido
    return sorted(vistos.values(), key=lambda par: par[0].quando, reverse=True)


def escolher(opcoes: list[tuple[backup.Backup, str]], resposta: str) -> backup.Backup | None:
    """Enter = o mais recente; senão o número da lista. None = resposta inválida."""
    resposta = resposta.strip()
    if not resposta:
        return opcoes[0][0]
    if resposta.isdigit() and 1 <= int(resposta) <= len(opcoes):
        return opcoes[int(resposta) - 1][0]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restaura um backup do ZERA CONTÁBIL MAX")
    parser.add_argument("arquivo", nargs="?", help="arquivo .dump (opcional)")
    args = parser.parse_args(argv)

    if not (RAIZ / ".env").exists():
        raise ErroAmigavel("O sistema ainda não foi instalado. Dê dois cliques no INSTALAR.bat primeiro.")
    if sistema_respondendo(f"http://127.0.0.1:{obter_config().porta}"):
        raise ErroAmigavel("O sistema está aberto. Feche a janela preta do INICIAR.bat e rode o RESTAURAR.bat de novo.")

    from scripts.banco_docker import preparar_banco

    preparar_banco()  # liga o banco e cria as tabelas (num computador novo, a cópia de segurança sai vazia)

    if args.arquivo:
        escolhido = Path(args.arquivo.strip('"'))
        if not escolhido.is_file():
            raise ErroAmigavel(f"Não encontrei o arquivo {escolhido}. Confira o caminho.")
    else:
        opcoes = backups_disponiveis()[: backup.MANTER]
        if not opcoes:
            raise ErroAmigavel(
                "Não encontrei nenhum backup. Se ele está no Google Drive, instale o Google Drive para "
                "computador, entre na conta do escritório e espere a pasta “Backups ZERA CONTABIL MAX” aparecer."
            )
        print("\nBackups encontrados (o mais recente primeiro):\n")
        for numero, (item, onde) in enumerate(opcoes, start=1):
            print(f"  {numero:2d})  {item.quando:%d/%m/%Y %H:%M}   {item.rotulo_motivo:<20} {onde}")
        while (escolhido := escolher(opcoes, input("\nNúmero do backup (Enter = 1, o mais recente): "))) is None:
            print(f"Digite um número de 1 a {len(opcoes)}.")
        escolhido = escolhido.caminho

    print(f"\nATENÇÃO: todos os dados atuais do sistema serão trocados pelos do backup {escolhido.name}.")
    print("Antes disso o sistema guarda uma cópia dos dados atuais (dá para voltar atrás).")
    if input(f"Para continuar, digite {CONFIRMACAO}: ").strip().upper() != CONFIRMACAO:
        print("\nNada foi alterado.")
        return 0

    try:
        print("\nGuardando uma cópia dos dados atuais...")
        seguranca = backup.fazer_backup("antes-de-restaurar", nuvem=False)
        print(f"Cópia guardada: {seguranca.backup.caminho}")
        print("Restaurando (pode levar alguns minutos)...")
        arquivos = backup.restaurar_backup(escolhido)
    except backup.ErroBackup as erro:
        raise ErroAmigavel(str(erro)) from erro

    from app.auditoria import registrar_evento
    from app.db import aplicar_migracoes, fabrica_sessoes

    aplicar_migracoes()  # um backup de uma versão antiga é atualizado para esta
    with fabrica_sessoes()() as sessao:
        registrar_evento(
            sessao,
            "RESTAURAR_BACKUP",
            detalhe=f"Restaurado o backup {escolhido.name}. Dados de antes guardados em {seguranca.backup.nome}.",
        )
        sessao.commit()
    print(f"\nPronto! Dados restaurados do backup {escolhido.name} ({arquivos} arquivos originais devolvidos).")
    print("Abra o sistema pelo INICIAR.bat.\n")
    return 0


if __name__ == "__main__":
    rodar(main)
