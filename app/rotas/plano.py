"""Aba “2 Plano de Contas” da empresa: importar, reimportar, copiar e pesquisar."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.modelos import Empresa, Usuario
from app.rotas.comum import buscar_empresa
from app.rotas.contas_chave import avisar_auto_configuracao
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.contas_chave import (
    CONFIANCA_ALTA,
    TIPOS_BANCARIOS,
    auto_configurar,
    contas_chave_da_empresa,
    nome_do_tipo,
)
from app.servicos.plano import (
    ErroLeitura,
    buscar_contas,
    contar_contas,
    descrever_resumo,
    empresas_com_plano,
    importar_plano,
    ler_plano,
    plano_de_outra_empresa,
    ultima_importacao,
)
from app.web import avisar, pagina, redirecionar

router = APIRouter()
TAMANHO_MAXIMO = 20 * 1024 * 1024  # um plano de contas tem poucas centenas de KB


def contexto_aba_plano(sessao: Session, empresa: Empresa, q: str = "", analiticas: bool = False) -> dict:
    total, total_analiticas = contar_contas(sessao, empresa)
    contas, encontradas = buscar_contas(sessao, empresa, q, analiticas) if total else ([], 0)
    lista_analiticas = buscar_contas(sessao, empresa, "", True, limite=5000)[0] if total else []
    return {
        "contas_chave": contas_chave_da_empresa(sessao, empresa),
        "nome_do_tipo": nome_do_tipo,
        "tipos_bancarios": TIPOS_BANCARIOS,
        "confianca_alta": CONFIANCA_ALTA,
        "lista_analiticas": lista_analiticas,
        "plano_total": total,
        "plano_analiticas": total_analiticas,
        "plano_ultima": ultima_importacao(sessao, empresa),
        "plano_contas": contas,
        "plano_encontradas": encontradas,
        "plano_q": q,
        "plano_so_analiticas": analiticas,
        "plano_outras_empresas": empresas_com_plano(sessao, empresa),
    }


def _destino(empresa: Empresa) -> str:
    return f"/empresas/{empresa.id}?aba=plano"


def _avisar_importacao(request: Request, texto: str, importacao) -> None:
    avisar(request, f"{texto}: {descrever_resumo(importacao.resumo)}.")
    if importacao.avisos:
        avisar(request, f"Há {len(importacao.avisos)} aviso(s) sobre o plano. Veja abaixo.", "atencao")


@router.post("/empresas/{empresa_id}/plano")
def enviar_plano(
    request: Request,
    empresa_id: int,
    arquivo: UploadFile | None = File(None),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if arquivo is None or not arquivo.filename:
        avisar(request, "Escolha o arquivo do plano de contas antes de clicar em Importar.", "erro")
        return redirecionar(_destino(empresa))
    conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        avisar(request, "O arquivo passa de 20 MB e não parece um plano de contas. Confira o arquivo.", "erro")
        return redirecionar(_destino(empresa))
    try:
        plano = ler_plano(conteudo, arquivo.filename)
    except ErroLeitura as erro:
        avisar(request, str(erro), "erro")
        return redirecionar(_destino(empresa))

    guardado = guardar_arquivo(sessao, empresa, "PLANO", arquivo.filename, conteudo, usuario)
    importacao = importar_plano(sessao, empresa, plano, usuario, guardado)
    sessao.commit()
    _avisar_importacao(request, f"Plano de contas importado ({plano.formato})", importacao)
    _configurar_sozinho(request, sessao, empresa, usuario)
    return redirecionar(_destino(empresa))


def _configurar_sozinho(request: Request, sessao: Session, empresa: Empresa, usuario: Usuario) -> None:
    """Logo depois de importar o plano o sistema descobre as contas-chave (§3.2.1), sem perguntar nada."""
    resultado = auto_configurar(sessao, empresa, usuario)
    sessao.commit()
    avisar_auto_configuracao(request, resultado)


@router.post("/empresas/{empresa_id}/plano/copiar")
def copiar_plano(
    request: Request,
    empresa_id: int,
    origem_id: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    origem = sessao.get(Empresa, int(origem_id)) if origem_id.isdigit() else None
    if origem is None or origem.id == empresa.id:
        avisar(request, "Escolha na lista a empresa de onde copiar o plano.", "erro")
        return redirecionar(_destino(empresa))
    try:
        plano = plano_de_outra_empresa(sessao, origem)
    except ErroLeitura as erro:
        avisar(request, str(erro), "erro")
        return redirecionar(_destino(empresa))
    importacao = importar_plano(sessao, empresa, plano, usuario)
    sessao.commit()
    _avisar_importacao(request, f"Plano copiado de {origem.nome}", importacao)
    _configurar_sozinho(request, sessao, empresa, usuario)
    return redirecionar(_destino(empresa))


@router.get("/empresas/{empresa_id}/plano/contas")
def linhas_do_plano(
    request: Request,
    empresa_id: int,
    q: str = "",
    analiticas: str = "",
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    """Pedaço da tabela para a busca instantânea (HTMX)."""
    empresa = sessao.get(Empresa, empresa_id)
    contas, encontradas = buscar_contas(sessao, empresa, q, bool(analiticas)) if empresa else ([], 0)
    return pagina(request, "_plano_linhas.html", plano_contas=contas, plano_encontradas=encontradas, plano_q=q)
