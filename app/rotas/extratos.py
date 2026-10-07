"""Aba “4 Extratos”: arrastar e soltar os extratos do mês, contas bancárias da empresa e movimentos lidos."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.modelos import Empresa, Usuario
from app.rotas.comum import buscar_empresa
from app.servicos.competencia import valor_campo_mes
from app.servicos.extratos import contas_bancarias, extratos_do_mes, importar_extrato, movimentos_do_mes
from app.servicos.plano import ErroLeitura
from app.web import avisar, redirecionar

router = APIRouter()
TAMANHO_MAXIMO = 30 * 1024 * 1024
CONFERENCIA = {
    "CONFERE": "saldo confere",
    "DIFERENCA": "saldo NÃO confere",
    "SEM_SALDO": "sem saldo para conferir",
}


def contexto_aba_extratos(sessao: Session, empresa: Empresa, competencia: date) -> dict:
    movimentos = movimentos_do_mes(sessao, empresa, competencia)
    return {
        "contas_bancarias": contas_bancarias(sessao, empresa),
        "extratos": extratos_do_mes(sessao, empresa, competencia),
        "movimentos": movimentos,
        "total_entradas": sum((m.valor for m in movimentos if m.sentido == "ENTRADA"), Decimal("0")),
        "total_saidas": sum((m.valor for m in movimentos if m.sentido == "SAIDA"), Decimal("0")),
        "rotulo_conferencia": CONFERENCIA,
    }


@router.post("/empresas/{empresa_id}/extratos")
def enviar_extratos(
    request: Request,
    empresa_id: int,
    arquivos: list[UploadFile] | None = File(None),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    destino = f"/empresas/{empresa.id}?aba=extratos"
    arquivos = [a for a in arquivos or [] if a.filename]
    if not arquivos:
        avisar(request, "Escolha (ou arraste) os arquivos dos extratos antes de enviar.", "erro")
        return redirecionar(destino)

    ultimo_mes = None
    for arquivo in arquivos:
        conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
        if len(conteudo) > TAMANHO_MAXIMO:
            avisar(request, f"{arquivo.filename}: passa de 30 MB. Envie o extrato de um mês por vez.", "erro")
            continue
        try:
            extrato = importar_extrato(sessao, empresa, arquivo.filename, conteudo, usuario)
        except ErroLeitura as erro:
            sessao.rollback()
            avisar(request, f"{arquivo.filename}: {erro}", "erro")
            continue
        sessao.commit()
        resumo = extrato.importacao.resumo
        texto = f"{arquivo.filename}: {extrato.conta_bancaria.rotulo}, {resumo['novos']} movimento(s) novo(s)"
        if resumo["repetidos"]:
            texto += f", {resumo['repetidos']} repetido(s) ignorado(s) (já estavam no sistema)"
        texto += f" — {CONFERENCIA[extrato.conferencia]}."
        avisar(
            request, texto, "ok" if extrato.conferencia == "CONFERE" and not extrato.importacao.avisos else "atencao"
        )
        ultimo_mes = extrato.fim.replace(day=1)
    if ultimo_mes:
        destino += f"&mes={valor_campo_mes(ultimo_mes)}"  # mostra o mês do extrato enviado
    return redirecionar(destino)
