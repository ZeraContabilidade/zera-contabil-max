"""Aba “5 Revisão”: a grade do mês com as sugestões; conferir, corrigir, aprovar ou ignorar linha a linha
(HTMX: só a linha muda) — e cada decisão ensina o sistema (§3.5, §6.3)."""

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.modelos import ContaContabil, Empresa, Sugestao, Usuario
from app.rotas.comum import buscar_empresa
from app.rotas.exportar import exportar_sozinho
from app.servicos.classificacao import classificar
from app.servicos.competencia import Periodo, periodo_no_arquivo, valor_campo_mes
from app.servicos.contas_chave import normalizar
from app.servicos.exportacao_automatica import meses_das_sugestoes
from app.servicos.fornecedores import lista, pela_linha
from app.servicos.perguntas import ler_respostas, planilha_perguntas
from app.servicos.plano import ErroLeitura
from app.servicos.revisao import (
    ACOES_LOTE,
    FILTROS,
    achar_conta_digitada,
    aprender_no_fim,
    aprovar,
    contagem_do_mes,
    contrapartida,
    corrigir,
    decidir_em_lote,
    ignorar,
    parecidas,
    reabrir,
    sugestoes_do_mes,
)
from app.web import avisar, competencia_da_tela, pagina, redirecionar

router = APIRouter()
ORIGENS = {
    "TRANSFERENCIA": "transferência entre contas",
    "REGRA": "regra do banco",
    "ESCRITORIO": "regra do escritório",
    "CNPJ": "pelo CNPJ",
    "NOME": "pelo nome",
    "PALAVRA": "palavra-chave",
    "VALOR": "pelo valor",
    "PENDENTE": "não reconhecido",
    "IA": "🤖 IA",
    "USUARIO": "escolhido à mão",
    "FORNECEDOR": "fornecedor novo",
}


def contas_para_escolher(sessao: Session, empresa: Empresa) -> list[tuple[str, str]]:
    """(“355 – ÁGUA E ESGOTO”, “355 – AGUA E ESGOTO”): o rótulo sem acento faz “agua” achar na lista."""
    contas = sessao.scalars(
        select(ContaContabil)
        .where(ContaContabil.empresa_id == empresa.id, ContaContabil.ativa, ContaContabil.tipo == "A")
        .order_by(ContaContabil.reduzido)
    )
    return [(c.rotulo, normalizar(c.rotulo)) for c in contas]


def contexto_aba_revisao(
    sessao: Session,
    empresa: Empresa,
    competencia: date | Periodo,
    filtro: str = "atencao",
    busca: str = "",
    conta: str = "",
) -> dict:
    filtro = filtro if filtro in FILTROS else "atencao"
    reduzido = int(conta) if conta.strip().isdigit() else None
    return {
        "sugestoes": sugestoes_do_mes(sessao, empresa, competencia, filtro, busca, reduzido),
        "contagem": contagem_do_mes(sessao, empresa, competencia),
        "filtros": FILTROS,
        "filtro": filtro,
        "busca_revisao": busca,
        "conta_filtro": conta,
        "contas_lista": contas_para_escolher(sessao, empresa),
        "origens": ORIGENS,
        "contrapartida": contrapartida,
        "fornecedores": lista(sessao, empresa),
    }


def _linha(request: Request, empresa: Empresa, sugestao: Sugestao, erro: str = "", outras=None, digitado=None):
    return pagina(
        request,
        "_revisao_linha.html",
        empresa=empresa,
        s=sugestao,
        erro=erro,
        digitado=digitado,  # com erro, a linha volta com o que foi digitado
        parecidas=outras or [],
        competencia=competencia_da_tela(request, None),  # “neste mês” ou “neste período”
        origens=ORIGENS,
        contrapartida=contrapartida,
    )


def _sugestao_da_empresa(sessao: Session, empresa: Empresa, sugestao_id: int) -> Sugestao | None:
    sugestao = sessao.get(Sugestao, sugestao_id)
    return sugestao if sugestao is not None and sugestao.empresa_id == empresa.id else None


@router.post("/empresas/{empresa_id}/revisao/lote")  # antes da rota com {sugestao_id}
def conferir_marcadas(
    request: Request,
    empresa_id: int,
    ids: list[str] = Form([]),
    acao: str = Form(""),
    conta: str = Form(""),
    mes: str = Form(""),
    filtro: str = Form(""),
    q: str = Form(""),
    conta_filtro: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    voltar = f"/empresas/{empresa.id}?" + urlencode(
        {"aba": "revisao", "mes": mes, "filtro": filtro, "q": q, "conta": conta_filtro}
    )
    marcadas = [int(i) for i in ids if i.strip().isdigit()]
    escolhida, erro = None, ""
    if not marcadas:
        erro = "Marque as linhas (caixinha à esquerda) antes de escolher o que fazer com elas."
    elif acao not in ACOES_LOTE:
        erro = "Escolha “Aplicar a conta”, “Aprovar” ou “Ignorar”."
    elif acao == "conta":
        escolhida, erro = achar_conta_digitada(sessao, empresa.id, conta)
    if erro:
        avisar(request, erro, "erro")
        return redirecionar(voltar)
    resultado = decidir_em_lote(sessao, empresa, marcadas, acao, escolhida, usuario)
    sessao.commit()
    exportar_sozinho(request, sessao, empresa, meses_das_sugestoes(sessao, marcadas))
    if acao == "conta":
        avisar(request, f"{escolhida.rotulo} aplicada a {resultado.feitas} linha(s).")
    else:
        avisar(request, f"{'Aprovada(s)' if acao == 'aprovar' else 'Ignorada(s)'} {resultado.feitas} linha(s).")
    if resultado.sem_conta:
        avisar(
            request, f"{resultado.sem_conta} linha(s) sem conta não foram aprovadas: escolha a conta primeiro.", "erro"
        )
    if resultado.exportadas:
        avisar(request, f"{resultado.exportadas} linha(s) já exportada(s) ficaram como estavam.", "erro")
    return redirecionar(voltar)


@router.post("/empresas/{empresa_id}/revisao/{sugestao_id}")
def conferir_linha(
    request: Request,
    empresa_id: int,
    sugestao_id: int,
    acao: str = Form(""),
    conta: str = Form(""),
    complemento: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    sugestao = _sugestao_da_empresa(sessao, empresa, sugestao_id)
    voltar = f"/empresas/{empresa.id}?aba=revisao"
    if sugestao is None or sugestao.status == "EXPORTADO":
        avisar(
            request,
            "Esta linha não pode mais ser mudada: já foi exportada (o Supervisor pode reabrir a exportação na aba "
            "Exportar) ou não existe.",
            "erro",
        )
        return redirecionar(voltar)
    erro, outras = "", []
    if acao == "salvar":
        escolhida, erro = achar_conta_digitada(sessao, empresa.id, conta)
        if escolhida is not None:
            mudou = contrapartida(sugestao) != escolhida
            corrigir(sessao, sugestao, escolhida, complemento, usuario)
            outras = parecidas(sessao, sugestao, competencia_da_tela(request, None)) if mudou else []
    elif acao == "aprovar":
        erro = aprovar(sessao, sugestao, usuario) or ""
    elif acao == "ignorar":
        ignorar(sessao, sugestao, usuario)
    elif acao == "reabrir":
        reabrir(sessao, sugestao)
    elif acao == "fornecedor":
        if empresa.terceiro_setor:
            erro = "Associação (terceiro setor) lança o pagamento direto na conta de despesa: escolha a conta."
        elif not empresa.usa_conta_individual:
            erro = "Esta empresa não usa conta individual por fornecedor (veja o Cadastro): escolha a conta."
        elif sugestao.movimento.sentido != "SAIDA":
            erro = "Só pagamentos (saídas) vão para a lista de fornecedores a cadastrar."
        elif pela_linha(sessao, empresa, sugestao) is None:
            erro = "Não achei o nome do fornecedor nesta linha: escolha a conta."
    else:
        erro = "Ação desconhecida."
    if erro:
        sessao.rollback()
        sugestao = sessao.get(Sugestao, sugestao_id)
    else:
        sessao.commit()
        exportar_sozinho(request, sessao, empresa, [sugestao.movimento.data.replace(day=1)])
    if request.headers.get("HX-Request"):
        digitado = {"conta": conta, "complemento": complemento} if erro and acao == "salvar" else None
        return _linha(request, empresa, sugestao, erro or "", outras, digitado)
    if erro:
        avisar(request, erro, "erro")
    return redirecionar(voltar)


@router.post("/empresas/{empresa_id}/revisao/{sugestao_id}/parecidas")
def aplicar_as_parecidas(
    request: Request,
    empresa_id: int,
    sugestao_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    sugestao = _sugestao_da_empresa(sessao, empresa, sugestao_id)
    periodo = competencia_da_tela(request, None)  # as parecidas do período da tela (o ano, se for o caso)
    if sugestao and not periodo.contem(sugestao.movimento.data):
        periodo = Periodo.do_mes(sugestao.movimento.data.replace(day=1))
    destino = f"/empresas/{empresa.id}?aba=revisao&mes={valor_campo_mes(periodo)}"
    escolhida = contrapartida(sugestao) if sugestao else None
    if escolhida is not None:
        outras = parecidas(sessao, sugestao, periodo)
        with aprender_no_fim(sessao):
            for outra in outras:
                corrigir(sessao, outra, escolhida, "", usuario)
        sessao.commit()
        avisar(request, f"{escolhida.rotulo} aplicada a mais {len(outras)} linha(s) parecida(s).")
        exportar_sozinho(request, sessao, empresa, [sugestao.movimento.data.replace(day=1)])
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": destino})
    return redirecionar(destino)


# ---------------------------------------------------------------- perguntas ao cliente
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/empresas/{empresa_id}/perguntas.xlsx")
def baixar_perguntas(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    periodo = competencia_da_tela(request, None)
    nome = f"perguntas_{empresa.codigo_arquivo}_{periodo_no_arquivo(periodo)}.xlsx"
    return Response(
        planilha_perguntas(sessao, empresa, periodo),
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.post("/empresas/{empresa_id}/perguntas")
def receber_respostas(
    request: Request,
    empresa_id: int,
    arquivo: UploadFile | None = File(None),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    destino = f"/empresas/{empresa.id}?aba=revisao&filtro=todos"
    if arquivo is None or not arquivo.filename:
        avisar(request, "Escolha a planilha de perguntas respondida pelo cliente antes de enviar.", "erro")
        return redirecionar(destino)
    try:
        resultado = ler_respostas(sessao, empresa, arquivo.file.read(10 * 1024 * 1024))
    except ErroLeitura as erro:
        sessao.rollback()
        avisar(request, str(erro), "erro")
        return redirecionar(destino)
    if resultado.respondidas:  # a resposta entra no histórico do lançamento; a IA olha de novo com ela
        datas = [s.movimento.data for s in resultado.respondidas]
        classificar(sessao, empresa, min(datas), max(datas))
        sessao.commit()
        avisar(request, resultado.resumo())
        from app.rotas.extratos import _ia_no_que_sobrou  # a IA usa a mesma rotina do envio de extratos

        _ia_no_que_sobrou(request, sessao, empresa, usuario, min(datas), max(datas))
    else:
        sessao.commit()
        avisar(request, resultado.resumo() + " Nenhuma resposta nova.", "atencao")
    return redirecionar(destino)
