"""Aba “3 Aprendizado”: importar o histórico, ver e corrigir o que o sistema aprendeu, perfil da empresa."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.ia.cliente import ErroIA
from app.ia.servico import IAIndisponivel
from app.modelos import ContaContabil, Empresa, Importacao, Padrao, Usuario
from app.rotas.comum import avisar_consulta, buscar_empresa
from app.servicos.aprendizado import (
    aprender,
    despesas_por_conta,
    gerar_perfil,
    importar_historico,
    listar_padroes,
    normalizar_natureza,
    resumo_historico,
)
from app.servicos.contas_chave import achar_conta_analitica
from app.servicos.empresas import completar_pelo_cnpj, descrever_campos
from app.servicos.historico_ia import contar_pendentes, revisar_historico
from app.servicos.plano import ErroLeitura, buscar_contas
from app.web import avisar, pagina, redirecionar

router = APIRouter()
TAMANHO_MAXIMO = 30 * 1024 * 1024


def contexto_aba_aprendizado(sessao: Session, empresa: Empresa, q: str = "", ambiguos: bool = False) -> dict:
    contas = sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)).all()
    return {
        "hist": resumo_historico(sessao, empresa),
        "importacoes_hist": sessao.scalars(
            select(Importacao)
            .where(Importacao.empresa_id == empresa.id, Importacao.tipo == "HISTORICO")
            .order_by(Importacao.id.desc())
            .limit(10)
        ).all(),
        "fornecedores": listar_padroes(sessao, empresa, "FORNECEDOR", q, ambiguos),
        "clientes": listar_padroes(sessao, empresa, "CLIENTE"),
        "palavras": listar_padroes(sessao, empresa, "PALAVRA"),
        "despesas": despesas_por_conta(sessao, empresa)[:30],
        "lista_analiticas": buscar_contas(sessao, empresa, "", True, limite=5000)[0] if contas else [],
        "rotulo_reduzido": {c.reduzido: c.rotulo for c in contas},
        "q_padroes": q,
        "so_ambiguos": ambiguos,
        "tem_plano": any(c.ativa for c in contas),
        "pendentes_ia": contar_pendentes(sessao, empresa),
    }


def _destino(empresa: Empresa, ancora: str = "") -> str:
    return f"/empresas/{empresa.id}?aba=aprendizado" + (f"#{ancora}" if ancora else "")


def _tentar_perfil(request: Request, sessao: Session, empresa: Empresa, usuario: Usuario) -> None:
    """Depois de aprender, a IA escreve o perfil da empresa. Sem IA, segue sem perfil (sem aviso)."""
    try:
        gerar_perfil(sessao, empresa, usuario)
        sessao.commit()
    except IAIndisponivel:
        sessao.rollback()
    except ErroIA as erro:
        sessao.rollback()
        avisar(request, f"Perfil da empresa não foi escrito agora: {erro}", "atencao")


@router.post("/empresas/{empresa_id}/historico")
def enviar_historico(
    request: Request,
    empresa_id: int,
    arquivo: UploadFile | None = File(None),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if arquivo is None or not arquivo.filename:
        avisar(request, "Escolha o arquivo do histórico antes de clicar em Importar.", "erro")
        return redirecionar(_destino(empresa))
    conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        avisar(request, "O arquivo passa de 30 MB. Divida em partes menores (por ano, por exemplo).", "erro")
        return redirecionar(_destino(empresa))
    try:
        importacao = importar_historico(sessao, empresa, arquivo.filename, conteudo, usuario)
    except ErroLeitura as erro:
        sessao.rollback()
        avisar(request, str(erro), "erro")
        return redirecionar(_destino(empresa))
    resumo = importacao.resumo
    preenchidos = resumo.get("preenchidos") or []
    consulta = completar_pelo_cnpj(empresa) if "cnpj_cpf" in preenchidos else None
    sessao.commit()  # a importação fica gravada antes da IA

    texto = f"Histórico importado: {resumo['novos']} lançamento(s) novo(s)"
    if resumo["repetidos"]:
        texto += f", {resumo['repetidos']} repetido(s) ignorado(s) (já estavam no sistema)"
    if resumo.get("completados"):
        texto += f", {resumo['completados']} completado(s) (estavam só com um lado, vindos do Diário)"
    avisar(request, texto + ".")
    if preenchidos:
        avisar(request, f"🤖 Preenchido pelo Diário: {descrever_campos(preenchidos)}.")
    if consulta:
        avisar_consulta(request, consulta)
    if importacao.avisos:
        avisar(request, f"Há {len(importacao.avisos)} aviso(s) sobre o arquivo. Veja abaixo.", "atencao")
    _revisar_com_ia(request, sessao, empresa, usuario, avisar_desligada=False)
    resultado = aprender(sessao, empresa)
    sessao.commit()
    avisar(request, resultado.resumo(), "atencao" if resultado.ambiguos else "ok")
    _tentar_perfil(request, sessao, empresa, usuario)
    return redirecionar(_destino(empresa))


def _revisar_com_ia(request: Request, sessao: Session, empresa: Empresa, usuario: Usuario, avisar_desligada: bool):
    """A IA completa o que as regras não separaram. Sem IA, tudo continua como estava."""
    try:
        revisao = revisar_historico(sessao, empresa, usuario)
    except IAIndisponivel as erro:
        sessao.rollback()
        if avisar_desligada:
            avisar(request, str(erro), "atencao")
        return
    sessao.commit()
    if revisao.revisados:
        avisar(request, revisao.resumo())
    if revisao.aviso:
        avisar(request, revisao.aviso, "atencao")


@router.post("/empresas/{empresa_id}/historico/ia")
def completar_historico_com_ia(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    _revisar_com_ia(request, sessao, empresa, usuario, avisar_desligada=True)
    resultado = aprender(sessao, empresa)
    sessao.commit()
    avisar(request, resultado.resumo(), "atencao" if resultado.ambiguos else "ok")
    return redirecionar(_destino(empresa))


@router.post("/empresas/{empresa_id}/aprendizado/refazer")
def refazer_aprendizado(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    resultado = aprender(sessao, empresa)
    sessao.commit()
    avisar(request, resultado.resumo())
    return redirecionar(_destino(empresa))


@router.post("/empresas/{empresa_id}/perfil")
def refazer_perfil(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    try:
        gerar_perfil(sessao, empresa, usuario)
        sessao.commit()
        avisar(request, "🤖 Perfil da empresa atualizado.")
    except ErroIA as erro:
        sessao.rollback()
        avisar(request, str(erro), "erro")
    return redirecionar(_destino(empresa, "perfil"))


@router.get("/empresas/{empresa_id}/aprendizado/padroes")
def linhas_padroes(
    request: Request,
    empresa_id: int,
    q: str = "",
    ambiguos: str = "",
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    """Pedaço da tabela de fornecedores para a busca instantânea (HTMX)."""
    empresa = sessao.get(Empresa, empresa_id)
    contexto = contexto_aba_aprendizado(sessao, empresa, q, bool(ambiguos)) if empresa else {"fornecedores": []}
    return pagina(request, "_padroes_linhas.html", empresa=empresa, padroes=contexto["fornecedores"], **contexto)


@router.post("/empresas/{empresa_id}/padroes/palavra")
def nova_palavra(
    request: Request,
    empresa_id: int,
    texto: str = Form(""),
    conta: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    chave = normalizar_natureza(texto)
    if len(chave) < 3:
        avisar(request, "Digite a palavra-chave com pelo menos 3 letras (ex.: TARIFA, GUIA DE FGTS).", "erro")
        return redirecionar(_destino(empresa, "palavras"))
    escolhida, erro = achar_conta_analitica(sessao, empresa.id, conta)
    if erro:
        avisar(request, erro, "erro")
        return redirecionar(_destino(empresa, "palavras"))
    padrao = sessao.scalar(
        select(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.tipo == "PALAVRA", Padrao.chave == chave)
    )
    if padrao is None:
        padrao = Padrao(empresa_id=empresa.id, tipo="PALAVRA", chave=chave, nome=" ".join(texto.upper().split()))
        sessao.add(padrao)
    padrao.conta_id, padrao.origem, padrao.ativo, padrao.ambiguo = escolhida.id, "USUARIO", True, False
    sessao.commit()
    avisar(request, f"Palavra-chave “{padrao.nome}” → {escolhida.rotulo}.")
    return redirecionar(_destino(empresa, "palavras"))


def _padrao_da_empresa(sessao: Session, request: Request, empresa_id: int, padrao_id: int):
    empresa = buscar_empresa(sessao, request, empresa_id)
    padrao = sessao.get(Padrao, padrao_id) if empresa else None
    if empresa and (padrao is None or padrao.empresa_id != empresa.id):
        avisar(request, "Padrão não encontrado.", "erro")
        padrao = None
    return empresa, padrao


@router.post("/empresas/{empresa_id}/padroes/{padrao_id}/conta")
def trocar_conta_do_padrao(
    request: Request,
    empresa_id: int,
    padrao_id: int,
    conta: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    empresa, padrao = _padrao_da_empresa(sessao, request, empresa_id, padrao_id)
    if empresa is None:
        return redirecionar("/")
    if padrao is not None:
        escolhida, erro = achar_conta_analitica(sessao, empresa.id, conta)
        if erro:
            avisar(request, erro, "erro")
        else:
            padrao.conta_id, padrao.conta = escolhida.id, escolhida
            padrao.origem, padrao.ambiguo = "USUARIO", False
            sessao.commit()
            avisar(request, f"{padrao.nome}: agora usa {escolhida.rotulo}. O sistema não muda mais sozinho.")
    return redirecionar(_destino(empresa, "fornecedores" if padrao and padrao.tipo != "PALAVRA" else "palavras"))


@router.post("/empresas/{empresa_id}/padroes/{padrao_id}/ativo")
def ligar_desligar_padrao(
    request: Request,
    empresa_id: int,
    padrao_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    empresa, padrao = _padrao_da_empresa(sessao, request, empresa_id, padrao_id)
    if empresa is None:
        return redirecionar("/")
    if padrao is not None:
        padrao.ativo = not padrao.ativo
        sessao.commit()
        avisar(request, f"{padrao.nome}: {'ativado' if padrao.ativo else 'desativado (não será mais usado)'}.")
    return redirecionar(_destino(empresa, "fornecedores" if padrao and padrao.tipo != "PALAVRA" else "palavras"))
