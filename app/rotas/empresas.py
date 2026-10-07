"""Lista de empresas (página inicial), cadastro e página da empresa com as abas do mês."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import exigir_supervisor, usuario_logado
from app.db import obter_sessao
from app.modelos import Empresa, Regime, Usuario
from app.rotas.aprendizado import contexto_aba_aprendizado
from app.rotas.comum import avisar_consulta, buscar_empresa
from app.rotas.plano import contexto_aba_plano
from app.servicos import backup
from app.servicos.complemento import EXEMPLO, montar_complemento
from app.servicos.empresas import (
    ResultadoConsulta,
    aplicar_edicao,
    buscar_empresas,
    completar_pelo_cnpj,
    ler_formulario,
)
from app.servicos.progresso import etapa_atual, progresso_do_mes
from app.web import avisar, competencia_da_tela, pagina, redirecionar

router = APIRouter()

ABAS = (
    ("cadastro", "Cadastro"),
    ("plano", "Plano de Contas"),
    ("aprendizado", "Aprendizado"),
    ("extratos", "Extratos"),
    ("revisao", "Revisão"),
    ("exportar", "Exportar"),
)
CHEGA_NA_ETAPA = {
    "extratos": "nas etapas 2.1 a 2.5 (leitura dos extratos)",
    "revisao": "na etapa 2.8 (tela de revisão)",
    "exportar": "na etapa 3.1 (geração do lanctos.txt)",
}


def _usuarios_ativos(sessao: Session) -> list[Usuario]:
    return list(sessao.scalars(select(Usuario).where(Usuario.ativo).order_by(Usuario.nome)))


def _linhas(sessao: Session, request: Request, q: str, minhas: str, usuario: Usuario, mes: str | None):
    competencia = competencia_da_tela(request, mes)
    empresas = buscar_empresas(sessao, q, usuario.id if minhas else None)
    linhas = []
    for empresa in empresas:
        etapas = progresso_do_mes(sessao, empresa, competencia)
        linhas.append({"empresa": empresa, "etapas": etapas, "atual": etapa_atual(etapas)})
    return linhas, competencia


@router.get("/")
def lista_empresas(
    request: Request,
    q: str = "",
    minhas: str = "",
    mes: str | None = None,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    linhas, competencia = _linhas(sessao, request, q, minhas, usuario, mes)
    total = sessao.scalar(select(func.count()).select_from(Empresa))
    return pagina(
        request,
        "empresas.html",
        linhas=linhas,
        q=q,
        minhas=bool(minhas),
        competencia=competencia,
        total=total,
        backup=backup.situacao() if usuario.e_supervisor else None,
    )


@router.get("/empresas/linhas")
def linhas_empresas(
    request: Request,
    q: str = "",
    minhas: str = "",
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    """Pedaço da tabela para a busca instantânea (HTMX)."""
    linhas, competencia = _linhas(sessao, request, q, minhas, usuario, None)
    return pagina(request, "_empresas_linhas.html", linhas=linhas, competencia=competencia, q=q)


def _tela_nova(request: Request, sessao: Session, dados: dict, erros: list[str], status_code: int = 200):
    return pagina(
        request,
        "empresa_nova.html",
        status_code=status_code,
        dados=dados,
        erros=erros,
        regimes=list(Regime),
        usuarios=_usuarios_ativos(sessao),
    )


@router.get("/empresas/nova")
def tela_nova_empresa(
    request: Request,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    return _tela_nova(request, sessao, dados={}, erros=[])


@router.post("/empresas")
def criar_empresa(
    request: Request,
    codigo_dominio: str = Form(""),
    cnpj_cpf: str = Form(""),
    razao_social: str = Form(""),
    nome_curto: str = Form(""),
    regime: str = Form(""),
    responsavel_id: str = Form(""),
    observacoes: str = Form(""),
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    form = {
        "codigo_dominio": codigo_dominio,
        "cnpj_cpf": cnpj_cpf,
        "razao_social": razao_social,
        "nome_curto": nome_curto,
        "regime": regime,
        "responsavel_id": responsavel_id,
        "observacoes": observacoes,
    }
    valores, erros = ler_formulario(sessao, form)
    if erros:
        return _tela_nova(request, sessao, dados=form, erros=erros, status_code=400)

    empresa = Empresa(**valores)
    resultado = completar_pelo_cnpj(empresa)
    sessao.add(empresa)
    sessao.commit()
    avisar(request, f"Empresa {empresa.nome} (código {empresa.codigo_dominio}) cadastrada.")
    avisar_consulta(request, resultado)
    return redirecionar(f"/empresas/{empresa.id}")


def _tela_empresa(
    request: Request,
    sessao: Session,
    empresa: Empresa,
    aba: str,
    mes: str | None = None,
    erros: list[str] | None = None,
    dados: dict | None = None,
    status_code: int = 200,
    **extras,
):
    competencia = competencia_da_tela(request, mes)
    aba = aba if aba in dict(ABAS) else "cadastro"
    modelo = (dados or {}).get("modelo_complemento") or empresa.modelo_complemento
    return pagina(
        request,
        "empresa.html",
        status_code=status_code,
        empresa=empresa,
        abas=ABAS,
        aba=aba,
        chega_na_etapa=CHEGA_NA_ETAPA.get(aba),
        competencia=competencia,
        etapas=progresso_do_mes(sessao, empresa, competencia),
        regimes=list(Regime),
        usuarios=_usuarios_ativos(sessao),
        erros=erros or [],
        dados=dados,
        exemplo_complemento=montar_complemento(modelo, EXEMPLO),
        **extras,
    )


@router.get("/empresas/{empresa_id}")
def tela_empresa(
    request: Request,
    empresa_id: int,
    aba: str = "cadastro",
    mes: str | None = None,
    q: str = "",
    analiticas: str = "",
    ambiguos: str = "",
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    extras = {}
    if aba == "plano":
        extras = contexto_aba_plano(sessao, empresa, q, bool(analiticas))
    elif aba == "aprendizado":
        extras = contexto_aba_aprendizado(sessao, empresa, q, bool(ambiguos))
    return _tela_empresa(request, sessao, empresa, aba, mes, **extras)


@router.post("/empresas/{empresa_id}")
def editar_empresa(
    request: Request,
    empresa_id: int,
    codigo_dominio: str = Form(""),
    cnpj_cpf: str = Form(""),
    razao_social: str = Form(""),
    nome_curto: str = Form(""),
    regime: str = Form(""),
    responsavel_id: str = Form(""),
    observacoes: str = Form(""),
    modelo_complemento: str = Form(""),
    ativa: str | None = Form(None),
    ia_ligada: str | None = Form(None),
    ia_limite_mensal_usd: str = Form(""),
    usa_conta_individual: str | None = Form(None),
    grupo_fornecedores: str = Form(""),
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    form = {
        "codigo_dominio": codigo_dominio,
        "cnpj_cpf": cnpj_cpf,
        "razao_social": razao_social,
        "nome_curto": nome_curto,
        "regime": regime,
        "responsavel_id": responsavel_id,
        "observacoes": observacoes,
        "modelo_complemento": modelo_complemento,
        "ativa": ativa,
        "ia_ligada": ia_ligada,
        "ia_limite_mensal_usd": ia_limite_mensal_usd,
        "usa_conta_individual": usa_conta_individual,
        "grupo_fornecedores": grupo_fornecedores,
    }
    valores, erros = ler_formulario(sessao, form, empresa)
    if erros:
        return _tela_empresa(request, sessao, empresa, "cadastro", erros=erros, dados=form, status_code=400)
    cnpj_mudou = valores["cnpj_cpf"] != empresa.cnpj_cpf
    aplicar_edicao(empresa, valores)
    resultado = completar_pelo_cnpj(empresa) if cnpj_mudou else ResultadoConsulta("sem_cnpj")
    sessao.commit()
    avisar(request, f"Cadastro de {empresa.nome} salvo.")
    avisar_consulta(request, resultado)
    return redirecionar(f"/empresas/{empresa.id}")


@router.post("/empresas/{empresa_id}/consultar-cnpj")
def consultar_cnpj_da_empresa(
    request: Request,
    empresa_id: int,
    supervisor: Usuario = Depends(exigir_supervisor),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    resultado = completar_pelo_cnpj(empresa)
    if resultado.situacao == "sem_cnpj":
        avisar(request, "Informe um CNPJ no cadastro para buscar os dados públicos.", "atencao")
    else:
        sessao.commit()
        if resultado.situacao == "ok" and not resultado.preenchidos:
            avisar(request, "Dados públicos do CNPJ atualizados. Nada mudou no cadastro.")
        avisar_consulta(request, resultado)
    return redirecionar(f"/empresas/{empresa.id}")
