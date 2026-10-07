"""Tela de backup (só Supervisor): onde ficam as cópias, as últimas feitas e o botão “Fazer backup agora”."""

from fastapi import APIRouter, Depends, Request

from app.auth import exigir_supervisor
from app.modelos import Usuario
from app.servicos import backup
from app.web import avisar, pagina, redirecionar

router = APIRouter()


@router.get("/backup")
def tela_backup(request: Request, supervisor: Usuario = Depends(exigir_supervisor)):
    return pagina(request, "backup.html", situacao=backup.situacao(), manter=backup.MANTER)


@router.post("/backup")
def fazer_backup_agora(request: Request, supervisor: Usuario = Depends(exigir_supervisor)):
    try:
        resultado = backup.fazer_backup("manual", supervisor.id)
    except backup.ErroBackup as erro:
        backup.registrar_falha(erro, supervisor.id)
        avisar(request, f"O backup não foi feito: {erro}", "erro")
    else:
        avisar(request, resultado.resumo(), "ok" if resultado.na_nuvem else "atencao")
    return redirecionar("/backup")
