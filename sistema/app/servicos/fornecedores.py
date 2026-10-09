"""Fornecedores a cadastrar no Domínio (§3.5, §6.2 passo 7).

Empresa com conta individual por fornecedor (ex.: Casa Criança, grupo 2.1.3.01): o pagamento a um fornecedor que
ainda não tem conta no plano não vai para uma conta qualquer — a linha fica PENDENTE, ligada ao fornecedor, e ele
entra na lista “Fornecedores a cadastrar no Domínio” (nome sugerido para a conta + CNPJ + grupo; baixa em Excel).
Quem manda para a lista: a IA (campo `conta_a_criar`) ou o usuário (botão “Fornecedor novo” na Revisão).

Sai da lista: (1) sozinho, quando o plano é reimportado com uma conta nova de nome parecido no grupo — as linhas
recebem a conta; (2) “Já cadastrei” com o código da conta — as linhas são corrigidas como na Revisão (ensinam);
(3) “Não é fornecedor” — as linhas voltam a pendentes sem conta.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import (
    ContaContabil,
    Empresa,
    FornecedorACadastrar,
    MovimentoExtrato,
    Sugestao,
    Usuario,
)
from app.servicos.aprendizado import CNPJ_NO_TEXTO, normalizar_nome
from app.servicos.classificacao import Proposta, complemento_da_proposta, semelhanca
from app.servicos.documentos import formatar_documento, normalizar_documento, tipo_documento
from app.servicos.revisao import aprender_no_fim, banco_do_movimento, corrigir

TAMANHO_NOME = 40  # o Domínio guarda a descrição da conta com 40 letras
NOME_PARECIDO = 90  # conta do plano com nome parecido a partir daqui = é a conta do fornecedor
CONFIANCA_CONTA_NOVA = 90


def nome_da_conta(texto: str | None) -> str:
    return " ".join((texto or "").upper().split())[:TAMANHO_NOME].strip()


def favorecido_da_linha(sugestao: Sugestao) -> str:
    """Como a linha mostra o favorecido: 1ª parte do complemento (“MERCEARIA ZETA - S/N”) ou o texto do banco."""
    movimento = sugestao.movimento
    return (sugestao.complemento or "").split(" - ")[0].strip() or movimento.complemento or movimento.historico


def documento_da_linha(movimento: MovimentoExtrato) -> str | None:
    """CNPJ/CPF só quando está escrito no extrato (e o dígito confere)."""
    texto = f"{movimento.historico} {movimento.complemento or ''} {movimento.documento or ''}"
    return next(
        (d for m in CNPJ_NO_TEXTO.finditer(texto) if tipo_documento(d := normalizar_documento(m.group(0)))), None
    )


def conta_parecida(sessao: Session, empresa_id: int, nome: str, grupo: str | None) -> ContaContabil | None:
    """A conta analítica do grupo de fornecedores cujo nome parece o do fornecedor (≥ 90)."""
    digitos = re.sub(r"\D", "", grupo or "")
    consulta = select(ContaContabil).where(
        ContaContabil.empresa_id == empresa_id, ContaContabil.ativa, ContaContabil.tipo == "A"
    )
    if digitos:
        consulta = consulta.where(ContaContabil.classificacao.startswith(digitos))
    notas = [(semelhanca(nome, c.descricao), -c.reduzido, c) for c in sessao.scalars(consulta)]
    nota, _, conta = max(notas, default=(0, 0, None), key=lambda n: n[:2])
    return conta if nota >= NOME_PARECIDO else None


def anotar(
    sessao: Session, empresa: Empresa, nome: str, cnpj: str | None, origem: str, justificativa: str = ""
) -> FornecedorACadastrar | None:
    """Põe o fornecedor na lista (uma vez só por nome). None = nome vazio, ou o usuário já disse que não é."""
    nome = nome_da_conta(nome)
    if not (chave := normalizar_nome(nome)):
        return None
    fornecedor = sessao.scalar(
        select(FornecedorACadastrar).where(
            FornecedorACadastrar.empresa_id == empresa.id, FornecedorACadastrar.chave == chave
        )
    )
    if fornecedor is None:
        fornecedor = FornecedorACadastrar(
            empresa_id=empresa.id,
            nome=nome,
            chave=chave,
            cnpj_cpf=cnpj,
            grupo=empresa.grupo_fornecedores,
            origem=origem,
            situacao="A_CADASTRAR",
            justificativa=justificativa[:2000] or None,
        )
        sessao.add(fornecedor)
        if conta := conta_parecida(sessao, empresa.id, nome, empresa.grupo_fornecedores):
            _cadastrado(fornecedor, conta)  # a conta já existia: não entra na lista
        sessao.flush()
        return fornecedor
    if fornecedor.situacao == "DESCARTADO":
        if origem != "USUARIO":
            return None  # o usuário já disse que não é fornecedor a cadastrar
        fornecedor.situacao, fornecedor.resolvido_em = "A_CADASTRAR", None
    fornecedor.cnpj_cpf = fornecedor.cnpj_cpf or cnpj
    return fornecedor


def _cadastrado(fornecedor: FornecedorACadastrar, conta: ContaContabil) -> None:
    fornecedor.situacao = "CADASTRADO"
    fornecedor.conta = conta
    fornecedor.resolvido_em = datetime.now(UTC)


def ligar(empresa: Empresa, sugestao: Sugestao, fornecedor: FornecedorACadastrar) -> None:
    """A linha passa a esperar a conta do fornecedor (ou já a recebe, se ele já foi cadastrado)."""
    sugestao.fornecedor = fornecedor
    sugestao.revisado_ia = True
    sugestao.padrao_id = None
    if fornecedor.situacao == "CADASTRADO" and fornecedor.conta is not None:
        _receber_conta(empresa, sugestao, fornecedor.conta)
        return
    movimento = sugestao.movimento
    banco = banco_do_movimento(movimento)
    if movimento.sentido == "SAIDA":
        sugestao.conta_debito, sugestao.conta_credito = None, banco
    else:
        sugestao.conta_debito, sugestao.conta_credito = banco, None
    onde = f" no grupo {fornecedor.grupo}" if fornecedor.grupo else ""
    sugestao.status, sugestao.confianca, sugestao.origem = "PENDENTE", 30, "FORNECEDOR"
    sugestao.justificativa = (
        f"Fornecedor sem conta no plano: cadastre “{fornecedor.nome}”{onde} no Domínio e reimporte o plano "
        "(lista “Fornecedores a cadastrar”)."
    )


def _receber_conta(empresa: Empresa, sugestao: Sugestao, conta: ContaContabil) -> None:
    movimento = sugestao.movimento
    banco = banco_do_movimento(movimento)
    if movimento.sentido == "SAIDA":
        sugestao.conta_debito, sugestao.conta_credito = conta, banco
    else:
        sugestao.conta_debito, sugestao.conta_credito = banco, conta
    sugestao.origem, sugestao.confianca = "FORNECEDOR", CONFIANCA_CONTA_NOVA
    sugestao.justificativa = f"Conta do fornecedor no plano: {conta.rotulo}."
    sugestao.status = "APROVADO" if CONFIANCA_CONTA_NOVA >= empresa.limiar_aprovacao else "PENDENTE"


def pela_linha(sessao: Session, empresa: Empresa, sugestao: Sugestao) -> FornecedorACadastrar | None:
    """Botão “Fornecedor novo” na Revisão: o favorecido da linha vai para a lista — e as outras linhas pendentes
    pagas a ele (mesmo nome) passam a esperar a mesma conta."""
    movimento = sugestao.movimento
    favorecido = favorecido_da_linha(sugestao)
    fornecedor = anotar(sessao, empresa, favorecido, documento_da_linha(movimento), "USUARIO", "Marcado na Revisão.")
    if fornecedor is None:
        return None
    ligar(empresa, sugestao, fornecedor)
    outras = sessao.scalars(
        select(Sugestao)
        .join(MovimentoExtrato, Sugestao.movimento_id == MovimentoExtrato.id)
        .where(
            Sugestao.empresa_id == empresa.id,
            Sugestao.id != sugestao.id,
            Sugestao.status == "PENDENTE",
            Sugestao.conferido_por_id.is_(None),
            Sugestao.fornecedor_id.is_(None),
            MovimentoExtrato.sentido == "SAIDA",
        )
    )
    chave = normalizar_nome(favorecido)
    for outra in outras:
        if normalizar_nome(favorecido_da_linha(outra)) == chave:
            ligar(empresa, outra, fornecedor)
    return fornecedor


def pela_ia(sessao: Session, empresa: Empresa, sugestao: Sugestao, nome: str, natureza: str, justificativa: str):
    """A IA disse que é um fornecedor novo (empresa com conta individual): lista + linha pendente esperando a conta."""
    movimento = sugestao.movimento
    cnpj = documento_da_linha(movimento)
    fornecedor = anotar(sessao, empresa, nome, cnpj, "IA", f"🤖 IA: {justificativa}" if justificativa else "")
    if fornecedor is None:
        return None
    proposta = Proposta(None, 30, "FORNECEDOR", "", favorecido=fornecedor.nome, cnpj=cnpj or "", natureza=natureza)
    sugestao.complemento = complemento_da_proposta(empresa, proposta, movimento)
    ligar(empresa, sugestao, fornecedor)
    return fornecedor


def _linhas_esperando(sessao: Session, fornecedor: FornecedorACadastrar) -> list[Sugestao]:
    return list(
        sessao.scalars(
            select(Sugestao).where(
                Sugestao.fornecedor_id == fornecedor.id,
                Sugestao.status != "EXPORTADO",
                Sugestao.conferido_por_id.is_(None),
            )
        )
    )


def dar_baixa(sessao: Session, empresa: Empresa) -> list[FornecedorACadastrar]:
    """Depois de reimportar o plano: quem ganhou conta (nome parecido no grupo) sai da lista e as linhas recebem a
    conta (aprovadas quando 90% ≥ o limiar da empresa)."""
    baixados = []
    for fornecedor in a_cadastrar(sessao, empresa):
        if (conta := conta_parecida(sessao, empresa.id, fornecedor.nome, fornecedor.grupo)) is None:
            continue
        _cadastrado(fornecedor, conta)
        for sugestao in _linhas_esperando(sessao, fornecedor):
            _receber_conta(empresa, sugestao, conta)
        baixados.append(fornecedor)
    sessao.flush()
    return baixados


def ja_cadastrei(
    sessao: Session, empresa: Empresa, fornecedor: FornecedorACadastrar, conta: ContaContabil, usuario: Usuario | None
) -> int:
    """O usuário informa a conta criada no Domínio: as linhas são corrigidas (e ensinam), como na Revisão."""
    _cadastrado(fornecedor, conta)
    linhas = _linhas_esperando(sessao, fornecedor)
    with aprender_no_fim(sessao):
        for sugestao in linhas:
            corrigir(sessao, sugestao, conta, "", usuario)
    return len(linhas)


def descartar(sessao: Session, fornecedor: FornecedorACadastrar) -> int:
    """“Não é fornecedor a cadastrar”: sai da lista e as linhas voltam a pendentes, para escolher a conta."""
    fornecedor.situacao = "DESCARTADO"
    fornecedor.resolvido_em = datetime.now(UTC)
    linhas = _linhas_esperando(sessao, fornecedor)
    for sugestao in linhas:
        sugestao.fornecedor = None
        sugestao.status, sugestao.confianca, sugestao.origem = "PENDENTE", 0, "PENDENTE"
        sugestao.justificativa = f"“{fornecedor.nome}” não é fornecedor a cadastrar: escolha a conta."
    return len(linhas)


# ---------------------------------------------------------------- lista e Excel


def a_cadastrar(sessao: Session, empresa: Empresa) -> list[FornecedorACadastrar]:
    return list(
        sessao.scalars(
            select(FornecedorACadastrar)
            .where(FornecedorACadastrar.empresa_id == empresa.id, FornecedorACadastrar.situacao == "A_CADASTRAR")
            .order_by(FornecedorACadastrar.nome)
        )
    )


@dataclass
class ItemLista:
    fornecedor: FornecedorACadastrar
    linhas: int
    valor: Decimal
    desde: date | None


def lista(sessao: Session, empresa: Empresa) -> list[ItemLista]:
    """Os fornecedores a cadastrar com as linhas que esperam por eles (quantas, quanto, desde quando)."""
    consulta = (
        select(Sugestao.fornecedor_id, func.count(), func.sum(MovimentoExtrato.valor), func.min(MovimentoExtrato.data))
        .join(MovimentoExtrato, Sugestao.movimento_id == MovimentoExtrato.id)
        .where(Sugestao.empresa_id == empresa.id, Sugestao.status == "PENDENTE", Sugestao.fornecedor_id.is_not(None))
        .group_by(Sugestao.fornecedor_id)
    )
    resumo = {fornecedor_id: (linhas, valor, desde) for fornecedor_id, linhas, valor, desde in sessao.execute(consulta)}
    itens = []
    for fornecedor in a_cadastrar(sessao, empresa):
        linhas, valor, desde = resumo.get(fornecedor.id, (0, Decimal("0"), None))
        itens.append(ItemLista(fornecedor, linhas, valor or Decimal("0"), desde))
    return itens


def planilha(sessao: Session, empresa: Empresa) -> bytes:
    """A lista em Excel, para cadastrar as contas no Domínio."""
    livro = Workbook()
    folha = livro.active
    folha.title = "Fornecedores a cadastrar"
    folha.append([f"Fornecedores a cadastrar no Domínio — {empresa.nome} (código {empresa.rotulo_codigo})"])
    folha["A1"].font = Font(bold=True, size=13)
    folha.append([f"Gerado em {datetime.now():%d/%m/%Y %H:%M}. Crie as contas e reimporte o plano no sistema."])
    folha.append([])
    titulos = ["Nome da conta a criar", "CNPJ/CPF", "Grupo (onde criar)", "Linhas pendentes", "Valor (R$)", "Desde"]
    folha.append([*titulos, "Sugerido por"])
    for celula in folha[4]:
        celula.font = Font(bold=True)
    for item in lista(sessao, empresa):
        f = item.fornecedor
        folha.append(
            [
                f.nome,
                formatar_documento(f.cnpj_cpf) if f.cnpj_cpf else "",
                f.grupo or "",
                item.linhas,
                item.valor,
                item.desde,
                "IA" if f.origem == "IA" else "Revisão",
            ]
        )
    for linha in folha.iter_rows(min_row=5):
        linha[4].number_format = "#,##0.00"
        linha[5].number_format = "DD/MM/YYYY"
    for coluna, largura in zip("ABCDEFG", (42, 20, 18, 16, 14, 12, 13), strict=True):
        folha.column_dimensions[coluna].width = largura
    saida = BytesIO()
    livro.save(saida)
    return saida.getvalue()
