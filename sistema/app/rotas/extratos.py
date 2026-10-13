"""Aba “4 Extratos”: arrastar e soltar os extratos do mês (ou do período), contas bancárias da empresa e movimentos
lidos.
Planilha (Excel/CSV) de layout novo: tela para confirmar as colunas e a conta, uma vez por layout."""

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.ia.servico import IAIndisponivel
from app.leitores.planilha import NOMES_PAPEIS, PAPEIS, texto_celula
from app.modelos import TIPOS_CONTA, ArquivoOriginal, ContaBancaria, Empresa, Extrato, Importacao, Usuario
from app.rotas.comum import buscar_empresa
from app.rotas.exportar import exportar_sozinho
from app.servicos.armazenamento import obter_armazenamento
from app.servicos.classificacao import classificar
from app.servicos.classificacao_ia import classificar_com_ia
from app.servicos.competencia import Periodo, hoje, valor_campo_mes
from app.servicos.contas_chave import BANCOS
from app.servicos.exportacao_automatica import meses_entre
from app.servicos.extratos import (
    contas_bancarias,
    extratos_do_mes,
    extratos_faltando,
    importar_extrato,
    mesma_conta,
    movimentos_do_mes,
)
from app.servicos.pasta_entrada import PastaInvalida, buscar_na_pasta, nao_lidos_sozinhos
from app.servicos.planilha_extrato import PrecisaConfirmar, analisar, guardar_modelo, problema_nas_colunas
from app.servicos.plano import ErroLeitura
from app.web import avisar, competencia_da_tela, pagina, redirecionar

router = APIRouter()
TAMANHO_MAXIMO = 30 * 1024 * 1024
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
}
CONFERENCIA = {
    "CONFERE": "saldo confere",
    "DIFERENCA": "saldo NÃO confere",
    "SEM_SALDO": "sem saldo para conferir",
}


def planilhas_esperando(sessao: Session, empresa: Empresa) -> list[ArquivoOriginal]:
    """Planilhas enviadas nos últimos 30 dias que ainda esperam a confirmação das colunas ou da conta."""
    importado = exists().where(Importacao.arquivo_id == ArquivoOriginal.id)
    return list(
        sessao.scalars(
            select(ArquivoOriginal)
            .where(
                ArquivoOriginal.empresa_id == empresa.id,
                ArquivoOriginal.tipo == "EXTRATO",
                ArquivoOriginal.enviado_em >= hoje() - timedelta(days=30),
                ~importado,
            )
            .order_by(ArquivoOriginal.id.desc())
        )
    )


def contexto_aba_extratos(sessao: Session, empresa: Empresa, competencia: date | Periodo) -> dict:
    movimentos = movimentos_do_mes(sessao, empresa, competencia)
    return {
        "contas_bancarias": contas_bancarias(sessao, empresa),
        "extratos": extratos_do_mes(sessao, empresa, competencia),
        "faltando": extratos_faltando(sessao, empresa, competencia),
        "movimentos": movimentos,
        "total_entradas": sum((m.valor for m in movimentos if m.sentido == "ENTRADA"), Decimal("0")),
        "total_saidas": sum((m.valor for m in movimentos if m.sentido == "SAIDA"), Decimal("0")),
        "rotulo_conferencia": CONFERENCIA,
        "planilhas_esperando": planilhas_esperando(sessao, empresa),
        "nao_lidos_da_pasta": nao_lidos_sozinhos(sessao, empresa) if empresa.pasta_extratos else [],
        "contagem": Counter({"verde": 0, "amarela": 0, "vermelha": 0, "cinza": 0})
        + Counter(m.sugestao.cor for m in movimentos if m.sugestao),
        "origens": ORIGENS,
    }


@router.post("/empresas/{empresa_id}/extratos/classificar")
def classificar_de_novo(
    request: Request,
    empresa_id: int,
    mes: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    periodo = competencia_da_tela(request, mes)
    resultado = classificar(sessao, empresa, *periodo.limites)
    sessao.commit()
    avisar(request, resultado.resumo())
    _ia_no_que_sobrou(request, sessao, empresa, usuario, *periodo.limites, avisar_desligada=True)
    exportar_sozinho(request, sessao, empresa, periodo.meses)
    return redirecionar(f"/empresas/{empresa.id}?aba=extratos&mes={valor_campo_mes(periodo)}")


def _ia_no_que_sobrou(request, sessao, empresa, usuario, inicio: date, fim: date, avisar_desligada=False) -> None:
    """A IA olha os pendentes e amarelos do período (§6.2 passo 6). Sem IA, tudo segue como está."""
    try:
        resultado = classificar_com_ia(sessao, empresa, usuario, inicio, fim)
    except IAIndisponivel as erro:
        sessao.rollback()
        if avisar_desligada:
            avisar(request, f"A IA não olhou os pendentes: {erro}", "atencao")
        return
    sessao.commit()
    if resultado.perguntadas:
        avisar(request, resultado.resumo())
    if resultado.aviso:
        avisar(request, resultado.aviso, "atencao")


def _avisar_importado(request: Request, nome: str, extrato: Extrato) -> None:
    resumo = extrato.importacao.resumo
    texto = f"{nome}: {extrato.conta_bancaria.rotulo}, {resumo['novos']} movimento(s) novo(s)"
    if resumo["repetidos"]:
        texto += f", {resumo['repetidos']} repetido(s) ignorado(s) (já estavam no sistema)"
    texto += f" — {CONFERENCIA[extrato.conferencia]}."
    if resumo.get("classificacao"):
        texto += f" {resumo['classificacao']}"
    ok = extrato.conferencia == "CONFERE" and not extrato.importacao.avisos
    avisar(request, texto, "ok" if ok else "atencao")


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

    confirmar, meses = [], set()
    for arquivo in arquivos:
        conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
        if len(conteudo) > TAMANHO_MAXIMO:
            avisar(request, f"{arquivo.filename}: passa de 30 MB. Envie o extrato de um mês por vez.", "erro")
            continue
        try:
            extrato = importar_extrato(sessao, empresa, arquivo.filename, conteudo, usuario)
        except PrecisaConfirmar as pedido:
            sessao.commit()  # o arquivo e a sugestão de colunas ficam guardados esperando a confirmação
            confirmar.append(pedido.arquivo.id)
            avisar(request, str(pedido), "atencao")
            continue
        except ErroLeitura as erro:
            sessao.rollback()
            avisar(request, f"{arquivo.filename}: {erro}", "erro")
            continue
        sessao.commit()
        _avisar_importado(request, arquivo.filename, extrato)
        _ia_no_que_sobrou(request, sessao, empresa, usuario, extrato.inicio, extrato.fim)
        meses.update(meses_entre(extrato.inicio, extrato.fim))
    exportar_sozinho(request, sessao, empresa, meses)
    if len(confirmar) == 1 and len(arquivos) == 1:
        return redirecionar(f"/empresas/{empresa.id}/extratos/planilha/{confirmar[0]}")
    if meses:  # mostra os meses dos extratos enviados (fica no período da tela se eles estão dentro dele)
        atual = competencia_da_tela(request, None)
        if not all(atual.contem(mes) for mes in meses):
            destino += f"&mes={valor_campo_mes(Periodo.entre(min(meses), max(meses)))}"
    return redirecionar(destino)


@router.post("/empresas/{empresa_id}/extratos/pasta")
def buscar_pasta_do_cliente(
    request: Request,
    empresa_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    """Lê os extratos novos da pasta do cliente (só leitura; o que já entrou é pulado)."""
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    destino = f"/empresas/{empresa.id}?aba=extratos"
    try:
        resultado = buscar_na_pasta(sessao, empresa, usuario)
    except PastaInvalida as erro:
        sessao.rollback()
        avisar(request, str(erro), "erro")
        return redirecionar(destino)
    sessao.commit()
    avisar(request, resultado.resumo(), "atencao" if resultado.erros or resultado.sem_leitor else "ok")
    if resultado.planilhas:
        avisar(
            request,
            f"{len(resultado.planilhas)} planilha(s) na pasta não foram lidas sozinhas (podem não ser extratos): "
            f"{', '.join(resultado.planilhas[:4])}. Se alguma for extrato, arraste-a na área de cima.",
            "atencao",
        )
    if resultado.sem_leitor:
        nomes = ", ".join(resultado.sem_leitor[:6]) + (" …" if len(resultado.sem_leitor) > 6 else "")
        avisar(
            request,
            f"{len(resultado.sem_leitor)} arquivo(s) de banco sem leitor próprio não foram lidos, para não gastar "
            f"IA sem você ver: {nomes}. Se precisar deles, arraste-os na área de cima — aí a IA lê (só entra se "
            "o saldo conferir).",
            "atencao",
        )
    if resultado.erros:
        detalhes = "; ".join(f"{nome}: {motivo}" for nome, motivo in resultado.erros[:4])
        mais = f" (e mais {len(resultado.erros) - 4})" if len(resultado.erros) > 4 else ""
        avisar(request, f"Não consegui ler {len(resultado.erros)} arquivo(s) — {detalhes}{mais}", "erro")
    if resultado.lidos:
        extratos = [extrato for _, extrato in resultado.lidos]
        inicio, fim = min(e.inicio for e in extratos), max(e.fim for e in extratos)
        _ia_no_que_sobrou(request, sessao, empresa, usuario, inicio, fim)
        meses = resultado.meses
        exportar_sozinho(request, sessao, empresa, meses)
        atual = competencia_da_tela(request, None)
        if not all(atual.contem(mes) for mes in meses):  # mostra os meses que chegaram
            destino += f"&mes={valor_campo_mes(Periodo.entre(min(meses), max(meses)))}"
    return redirecionar(destino)


# ---------------------------------------------------------------- confirmação de planilha


def _arquivo_esperando(sessao: Session, request: Request, empresa: Empresa, arquivo_id: int) -> ArquivoOriginal | None:
    arquivo = sessao.get(ArquivoOriginal, arquivo_id)
    if arquivo is None or arquivo.empresa_id != empresa.id or arquivo.tipo != "EXTRATO":
        avisar(request, "Planilha não encontrada. Envie o arquivo de novo.", "erro")
        return None
    return arquivo


def _tela_confirmar(request, sessao, empresa, arquivo, analise, erros=None, dados=None, status_code=200):
    contas = contas_bancarias(sessao, empresa)
    sugerida = next((c.id for c in contas if c.assinatura_planilha == analise.assinatura), None)
    if dados is None and (escrito := analise.banco_no_arquivo):  # banco, agência e conta escritos na planilha
        dados = {"nova_banco": escrito["banco"], "nova_agencia": escrito["agencia"], "nova_numero": escrito["numero"]}
        existente = next((c for c in contas if mesma_conta(c, escrito["agencia"], escrito["numero"])), None)
        if existente:
            sugerida = existente.id
        elif sugerida is None:
            dados["conta"] = "nova"
    fim_amostra = max(analise.linha_titulos, 0) + 12
    return pagina(
        request,
        "planilha_confirmar.html",
        status_code=status_code,
        empresa=empresa,
        arquivo=arquivo,
        analise=analise,
        amostra=[[texto_celula(c) for c in linha] for linha in analise.linhas[:fim_amostra]],
        largura=max((len(linha) for linha in analise.linhas[:fim_amostra]), default=0),
        papeis=[(papel, NOMES_PAPEIS[papel]) for papel in PAPEIS],
        contas=contas,
        conta_sugerida=sugerida,
        bancos=[(codigo, nome) for codigo, _, nome, _ in BANCOS],
        tipos=TIPOS_CONTA,
        erros=erros or [],
        dados=dados or {},
    )


@router.get("/empresas/{empresa_id}/extratos/planilha/{arquivo_id}")
def tela_confirmar_planilha(
    request: Request,
    empresa_id: int,
    arquivo_id: int,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if (arquivo := _arquivo_esperando(sessao, request, empresa, arquivo_id)) is None:
        return redirecionar(f"/empresas/{empresa.id}?aba=extratos")
    conteudo = obter_armazenamento().ler(arquivo.chave)
    analise = analisar(sessao, empresa, usuario, conteudo)
    sessao.commit()
    return _tela_confirmar(request, sessao, empresa, arquivo, analise)


@router.post("/empresas/{empresa_id}/extratos/planilha/{arquivo_id}")
def confirmar_planilha(
    request: Request,
    empresa_id: int,
    arquivo_id: int,
    linha_titulos: str = Form(""),
    col_data: str = Form(""),
    col_historico: str = Form(""),
    col_complemento: str = Form(""),
    col_documento: str = Form(""),
    col_valor: str = Form(""),
    col_debito: str = Form(""),
    col_credito: str = Form(""),
    col_sentido: str = Form(""),
    col_saldo: str = Form(""),
    conta: str = Form(""),
    nova_banco: str = Form(""),
    nova_agencia: str = Form(""),
    nova_numero: str = Form(""),
    nova_tipo: str = Form(""),
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
):
    if (empresa := buscar_empresa(sessao, request, empresa_id)) is None:
        return redirecionar("/")
    if (arquivo := _arquivo_esperando(sessao, request, empresa, arquivo_id)) is None:
        return redirecionar(f"/empresas/{empresa.id}?aba=extratos")
    formulario = {nome: str(valor).strip() for nome, valor in locals().items() if isinstance(valor, str)}
    conteudo = obter_armazenamento().ler(arquivo.chave)
    analise = analisar(sessao, empresa, usuario, conteudo)

    def numero(campo: str, padrao: int = -1) -> int:
        try:
            return int(formulario.get(campo, padrao))
        except ValueError:
            return padrao

    colunas = {papel: numero(f"col_{papel}") for papel in PAPEIS}
    linha_titulos = numero("linha_titulos", analise.linha_titulos)
    erros = [problema] if (problema := problema_nas_colunas(colunas)) else []
    escolha = formulario.get("conta", "")
    escolhida: ContaBancaria | dict[str, str] | None = None
    if escolha.isdigit():
        escolhida = sessao.get(ContaBancaria, int(escolha))
        if escolhida is None or escolhida.empresa_id != empresa.id:
            erros.append("Escolha a conta bancária na lista.")
    elif escolha == "nova":
        banco, numero_conta = formulario.get("nova_banco", ""), formulario.get("nova_numero", "")
        if banco not in {codigo for codigo, *_ in BANCOS} or not numero_conta:
            erros.append("Para uma conta nova, escolha o banco e informe o número da conta.")
        escolhida = {
            "banco": banco,
            "agencia": formulario.get("nova_agencia", ""),
            "numero": numero_conta,
            "tipo": formulario.get("nova_tipo") if formulario.get("nova_tipo") in TIPOS_CONTA else "BANCO",
        }
    else:
        erros.append("Escolha de qual conta bancária é a planilha.")
    if erros:
        return _tela_confirmar(request, sessao, empresa, arquivo, analise, erros, formulario, 400)

    guardar_modelo(sessao, analise, colunas, linha_titulos, usuario)
    try:
        extrato = importar_extrato(sessao, empresa, arquivo.nome_original, conteudo, usuario, escolhida, arquivo)
    except ErroLeitura as erro:
        sessao.rollback()
        analise = analisar(sessao, empresa, usuario, conteudo)
        return _tela_confirmar(request, sessao, empresa, arquivo, analise, [str(erro)], formulario, 400)
    sessao.commit()
    _avisar_importado(request, arquivo.nome_original, extrato)
    _ia_no_que_sobrou(request, sessao, empresa, usuario, extrato.inicio, extrato.fim)
    return redirecionar(f"/empresas/{empresa.id}?aba=extratos&mes={valor_campo_mes(extrato.fim.replace(day=1))}")
