"""Aba “6 Exportar”: o lanctos.txt do mês ou do período (ex.: o ano todo) para importar no Domínio (§3.6) + resumo
em Excel + histórico."""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import exigir_supervisor, usuario_logado
from app.db import obter_sessao
from app.modelos import Empresa, Exportacao, Usuario
from app.rotas.comum import buscar_empresa
from app.servicos.armazenamento import ArquivoApagado, ler_arquivo
from app.servicos.competencia import (
    Periodo,
    como_periodo,
    ler_periodo,
    nome_competencia,
    periodo_no_arquivo,
    valor_campo_mes,
)
from app.servicos.conferencia_dominio import informar_saldos, linhas_conferencia
from app.servicos.exportacao import (
    ErroExportacao,
    exportacoes,
    exportar,
    preparar,
    reabrir_exportacao,
    resumo_excel,
)
from app.servicos.exportacao_automatica import exportar_se_pronto, motivo_para_esperar
from app.web import avisar, competencia_da_tela, redirecionar

router = APIRouter()
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def ler_ids(valores: list[str]) -> list[int]:
    return [int(v) for v in valores if v.strip().isdigit()]


def contexto_aba_exportar(sessao: Session, empresa: Empresa, competencia: date | Periodo, bancos: list[int]) -> dict:
    periodo = como_periodo(competencia)
    preparo = preparar(sessao, empresa, periodo, bancos)
    return {
        "preparo": preparo,
        "escolhidas_ids": [c.id for c in preparo.escolhidas],
        "exportacoes": exportacoes(sessao, empresa),
        "conferencia": linhas_conferencia(sessao, empresa, periodo),
        "espera_automatica": motivo_para_esperar(sessao, empresa, periodo.inicio)
        if empresa.exportacao_automatica and periodo.um_mes  # a automática é sempre mês a mês
        else None,
    }


def exportar_sozinho(request: Request, sessao: Session, empresa: Empresa, competencias: Iterable[date]) -> None:
    """Depois de uma mudança no mês: exportação automática ligada + mês pronto → o lanctos.txt sai sozinho (§6.5)."""
    if not empresa.exportacao_automatica:
        return
    for competencia in sorted(set(competencias)):
        try:
            exportacao = exportar_se_pronto(sessao, empresa, competencia)
        except ErroExportacao:
            sessao.rollback()
            continue
        if exportacao is not None:
            sessao.commit()
            avisar(
                request,
                f"🤖 Exportação automática: o lanctos.txt de {nome_competencia(competencia)} foi gerado sozinho "
                f"({exportacao.linhas} lançamento(s)). Baixe na aba Exportar e importe no Domínio.",
                "festa",
            )


@router.post("/empresas/{empresa_id}/exportar")
def gerar_lanctos(
    request: Request,
    empresa_id: int,
    mes: str = Form(""),
    bancos: list[str] = Form([]),
    deixar_pendentes: str | None = Form(None),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    periodo = ler_periodo(mes) or competencia_da_tela(request, None)
    ids = ler_ids(bancos)
    voltar = f"/empresas/{empresa.id}?" + urlencode(
        [("aba", "exportar"), ("mes", valor_campo_mes(periodo)), *[("bancos", i) for i in ids]]
    )
    try:
        exportacao = exportar(sessao, empresa, periodo, ids, usuario, deixar_pendentes is not None)
    except ErroExportacao as erro:
        sessao.rollback()
        avisar(request, str(erro), "erro")
        return redirecionar(voltar)
    sessao.commit()
    avisar(
        request,
        f"lanctos.txt gerado: {exportacao.linhas} lançamento(s). Baixe o arquivo abaixo e importe no Domínio; "
        "as linhas exportadas ficaram travadas.",
        "festa",
    )
    return redirecionar(voltar)


@router.post("/empresas/{empresa_id}/exportacoes/{exportacao_id}/reabrir")
def reabrir(
    request: Request,
    empresa_id: int,
    exportacao_id: int,
    motivo: str = Form(""),
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if (exportacao := _exportacao_da_empresa(sessao, empresa, exportacao_id)) is None:
        avisar(request, "Exportação não encontrada.", "erro")
        return redirecionar(f"/empresas/{empresa.id}?aba=exportar")
    voltar = f"/empresas/{empresa.id}?" + urlencode({"aba": "exportar", "mes": valor_campo_mes(exportacao.periodo)})
    try:
        linhas = reabrir_exportacao(sessao, exportacao, supervisor, motivo)
    except ErroExportacao as erro:
        sessao.rollback()
        avisar(request, str(erro), "erro")
        return redirecionar(voltar)
    sessao.commit()
    avisar(
        request,
        f"Exportação reaberta: {linhas} linha(s) voltaram para a Revisão como aprovadas. Corrija o que for preciso e "
        "gere o arquivo de novo. Se o arquivo antigo já foi importado no Domínio, exclua lá aqueles lançamentos antes.",
    )
    return redirecionar(voltar)


def _exportacao_da_empresa(sessao: Session, empresa: Empresa, exportacao_id: int) -> Exportacao | None:
    exportacao = sessao.get(Exportacao, exportacao_id)
    return exportacao if exportacao is not None and exportacao.empresa_id == empresa.id else None


@router.get("/empresas/{empresa_id}/exportacoes/{exportacao_id}/lanctos.txt")
def baixar_lanctos(
    request: Request,
    empresa_id: int,
    exportacao_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if (exportacao := _exportacao_da_empresa(sessao, empresa, exportacao_id)) is None:
        avisar(request, "Exportação não encontrada.", "erro")
        return redirecionar(f"/empresas/{empresa.id}?aba=exportar")
    arquivo = exportacao.arquivo
    try:
        conteudo = ler_arquivo(arquivo)
    except ArquivoApagado as erro:
        avisar(request, str(erro), "erro")
        return redirecionar(f"/empresas/{empresa.id}?aba=exportar")
    if exportacao.baixado_em is None:  # o aviso “pronto para importar” do Painel some
        exportacao.baixado_em = datetime.now(UTC)
        sessao.commit()
    return Response(
        conteudo,
        media_type="text/plain; charset=windows-1252",
        headers={"Content-Disposition": f'attachment; filename="{arquivo.nome_original}"'},
    )


@router.get("/empresas/{empresa_id}/exportacoes/{exportacao_id}/resumo.xlsx")
def baixar_resumo(
    request: Request,
    empresa_id: int,
    exportacao_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if (exportacao := _exportacao_da_empresa(sessao, empresa, exportacao_id)) is None:
        avisar(request, "Exportação não encontrada.", "erro")
        return redirecionar(f"/empresas/{empresa.id}?aba=exportar")
    nome = f"resumo_{empresa.codigo_arquivo}_{periodo_no_arquivo(exportacao.periodo)}.xlsx"
    return Response(
        resumo_excel(sessao, empresa, exportacao),
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.post("/empresas/{empresa_id}/conferencia-dominio")
async def conferir_com_o_dominio(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    """Os saldos digitados (um campo “saldo-<conta>-<AAAA-MM>” por conta e mês) → compara com o extrato."""
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    formulario = await request.form()
    periodo = competencia_da_tela(request, str(formulario.get("mes") or "") or None)
    digitados = {
        chave.removeprefix("saldo-"): str(valor) for chave, valor in formulario.items() if chave.startswith("saldo-")
    }
    gravadas, erros = informar_saldos(sessao, empresa, periodo, digitados, usuario)
    sessao.commit()
    for erro in erros:
        avisar(request, erro, "erro")
    if gravadas:
        diferentes = [linha for linha in gravadas if linha.situacao == "DIFERENCA"]
        if diferentes:
            detalhes = "; ".join(f"{linha.conta.rotulo}: {linha.texto_diferenca}" for linha in diferentes)
            avisar(request, f"Conferência com o Domínio: {len(diferentes)} conta(s) não batem — {detalhes}.", "erro")
        else:
            avisar(request, f"Conferência com o Domínio: as {len(gravadas)} conta(s) batem com o extrato. 🎉", "festa")
    destino = f"/empresas/{empresa.id}?" + urlencode({"aba": "exportar", "mes": valor_campo_mes(periodo)})
    return redirecionar(destino + "#conferencia")
