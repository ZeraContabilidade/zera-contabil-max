"""Extrato em Excel/CSV (§3.4, regras 3 e 5): as colunas de cada layout e a conta bancária.

1. Colunas: o modelo já confirmado daquele layout (assinatura dos títulos); senão os títulos comuns
   (“Data”, “Histórico”, “Valor”...); senão a IA (modelo rápido) olha as primeiras linhas.
2. Na 1ª vez de um layout o usuário CONFIRMA as colunas numa tela (o arquivo fica guardado esperando);
   depois o modelo vale para qualquer empresa.
3. Conta bancária: banco/agência/conta escritos no alto da planilha; senão a conta da empresa que já usou
   este layout; senão o usuário escolhe na mesma tela de confirmação.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import chamar_ia
from app.leitores import ExtratoLido
from app.leitores.planilha import (
    PAPEIS,
    achar_titulos,
    assinatura,
    completar,
    ler_linhas,
    montar,
    texto_celula,
    titulos,
)
from app.modelos import ArquivoOriginal, ContaBancaria, Empresa, ModeloPlanilha, Usuario
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.contas_chave import identificar_banco
from app.servicos.plano import ErroLeitura

AMOSTRA = 15  # linhas mostradas à IA e na tela de confirmação


class PrecisaConfirmar(ErroLeitura):
    """1ª vez deste layout (ou conta bancária desconhecida): o arquivo ficou guardado esperando a confirmação."""

    def __init__(self, arquivo: ArquivoOriginal, motivo: str):
        super().__init__(f"{arquivo.nome_original}: {motivo}")
        self.arquivo = arquivo


@dataclass
class Analise:
    linhas: list[list[Any]]
    linha_titulos: int
    colunas: dict[str, int]
    assinatura: str
    titulos: list[str]
    modelo: ModeloPlanilha | None
    origem: str  # MODELO, TITULOS, IA ou NENHUMA
    aviso_ia: str = ""
    banco_no_arquivo: dict[str, str] = field(default_factory=dict)

    @property
    def colunas_validas(self) -> bool:
        return problema_nas_colunas(self.colunas) is None


def problema_nas_colunas(colunas: dict[str, int]) -> str | None:
    if colunas.get("data", -1) < 0:
        return "Escolha a coluna da data."
    if colunas.get("historico", -1) < 0:
        return "Escolha a coluna do histórico (descrição)."
    if colunas.get("valor", -1) < 0 and (colunas.get("debito", -1) < 0 or colunas.get("credito", -1) < 0):
        return "Escolha a coluna do valor, ou as duas colunas de débito e de crédito."
    return None


# ---------------------------------------------------------------- colunas

INSTRUCOES_COLUNAS = """Você identifica as colunas de um extrato bancário em planilha (Excel ou CSV) exportado por \
um banco brasileiro. Recebe as primeiras linhas, numeradas, com as células separadas por " | " (a primeira coluna é \
a 0). Responda só o JSON:
- linha_titulos: o número da linha com os títulos das colunas (-1 se a planilha não tiver títulos);
- para cada papel, o número da coluna (-1 se não existir): data (do lançamento), historico (descrição ou tipo do \
lançamento), complemento (favorecido ou detalhe, quando vier em outra coluna), documento, valor (valor com sinal, \
ou sem sinal quando houver coluna C/D), debito (coluna só das saídas), credito (coluna só das entradas), sentido \
(coluna com C ou D), saldo.
Use valor OU debito e credito. Nunca aponte uma coluna que não existe."""

ESQUEMA_COLUNAS = {
    "type": "object",
    "properties": {"linha_titulos": {"type": "integer"}, **{papel: {"type": "integer"} for papel in PAPEIS}},
    "required": ["linha_titulos", *PAPEIS],
    "additionalProperties": False,
}


def _amostra(linhas: list[list[Any]]) -> str:
    return "\n".join(
        f"linha {i}: " + " | ".join(texto_celula(c) for c in linha) for i, linha in enumerate(linhas[:AMOSTRA])
    )


def _colunas_pela_ia(
    sessao: Session, empresa: Empresa, usuario: Usuario | None, linhas: list[list[Any]]
) -> tuple[int, dict[str, int]]:
    pedido = PedidoIA(
        finalidade="colunas_planilha",
        instrucoes=INSTRUCOES_COLUNAS,
        pergunta=_amostra(linhas),
        esquema=ESQUEMA_COLUNAS,
        max_tokens=1000,
    )
    dados = chamar_ia(sessao, pedido, empresa, usuario).dados
    largura = max((len(linha) for linha in linhas[:AMOSTRA]), default=0)
    colunas = {p: int(dados.get(p, -1)) if -1 <= int(dados.get(p, -1)) < largura else -1 for p in PAPEIS}
    linha_titulos = int(dados.get("linha_titulos", -1))
    return (linha_titulos if -1 <= linha_titulos < min(len(linhas), AMOSTRA) else -1), colunas


def analisar(sessao: Session, empresa: Empresa, usuario: Usuario | None, conteudo: bytes) -> Analise:
    linhas = ler_linhas(conteudo)
    if len(linhas) < 2:
        raise ErroLeitura("A planilha está vazia ou tem uma linha só. Confira se exportou o extrato certo.")
    # 1) um modelo já conhecido: a assinatura de alguma das primeiras linhas bate com a de um modelo
    candidatas = {assinatura(linhas, i): i for i in range(min(len(linhas), 30))}
    candidatas.setdefault(assinatura(linhas, -1), -1)  # planilha sem títulos
    modelo = sessao.scalar(select(ModeloPlanilha).where(ModeloPlanilha.assinatura.in_(candidatas)))
    if modelo is not None:
        linha = candidatas[modelo.assinatura]
        origem = "MODELO" if modelo.confirmado else modelo.origem  # sugestão ainda não confirmada: quem sugeriu
        analise = Analise(linhas, linha, completar(modelo.colunas), modelo.assinatura, titulos(linhas, linha),
                          modelo, origem)  # fmt: skip
    elif achado := achar_titulos(linhas):  # 2) os títulos comuns
        linha, colunas = achado
        analise = Analise(linhas, linha, colunas, assinatura(linhas, linha), titulos(linhas, linha), None, "TITULOS")
    else:  # 3) a IA olha as primeiras linhas
        aviso, linha, colunas = "", -1, completar({})
        try:
            linha, colunas = _colunas_pela_ia(sessao, empresa, usuario, linhas)
            origem = "IA"
        except ErroIA as erro:
            aviso, origem = f"A IA não ajudou a achar as colunas ({erro}). Escolha você mesmo.", "NENHUMA"
        analise = Analise(linhas, linha, colunas, assinatura(linhas, linha), titulos(linhas, linha), None, origem,
                          aviso)  # fmt: skip
    analise.banco_no_arquivo = _banco_no_cabecalho(linhas[: max(analise.linha_titulos, 0)])
    return analise


def _banco_no_cabecalho(linhas: list[list[Any]]) -> dict[str, str]:
    """Banco, agência e conta escritos acima dos títulos (“Agência: 1234-5  Conta: 12345-6”)."""
    texto = " ".join(texto_celula(c) for linha in linhas for c in linha)
    banco = identificar_banco(texto)
    agencia = re.search(r"Ag[eê]ncia\s*:?\s*(\d{1,5}(?:-[\dXx])?)", texto, re.IGNORECASE)
    conta = re.search(r"Conta(?:\s+corrente)?\s*:?\s*([\d.]{3,}-[\dXx])", texto, re.IGNORECASE)
    if not (banco and conta):
        return {}
    return {"banco": banco[0], "agencia": agencia.group(1) if agencia else "", "numero": conta.group(1)}


def guardar_modelo(sessao: Session, analise: Analise, colunas: dict[str, int], linha_titulos: int,
                   usuario: Usuario | None) -> ModeloPlanilha:  # fmt: skip
    """O usuário confirmou: o layout fica conhecido (para qualquer empresa)."""
    marca = assinatura(analise.linhas, linha_titulos)
    modelo = sessao.scalar(select(ModeloPlanilha).where(ModeloPlanilha.assinatura == marca))
    if modelo is None:
        modelo = ModeloPlanilha(assinatura=marca, origem="USUARIO")
        sessao.add(modelo)
    mudou = completar(colunas) != analise.colunas or linha_titulos != analise.linha_titulos
    if mudou or modelo.origem == "NENHUMA":
        modelo.origem = "USUARIO"
    modelo.titulos = titulos(analise.linhas, linha_titulos)
    modelo.linha_titulos = linha_titulos
    modelo.colunas = completar(colunas)
    modelo.confirmado = True
    modelo.confirmado_por_id = usuario.id if usuario else None
    modelo.confirmado_em = datetime.now(UTC)
    sessao.flush()
    return modelo


# ---------------------------------------------------------------- leitura


def ler_planilha_extrato(
    sessao: Session,
    empresa: Empresa,
    usuario: Usuario | None,
    nome: str,
    conteudo: bytes,
    conta: ContaBancaria | dict[str, str] | None = None,
) -> ExtratoLido:
    """ExtratoLido da planilha. Levanta PrecisaConfirmar (com o arquivo guardado) quando o layout é novo
    ou quando não dá para saber de qual conta bancária ela é."""
    analise = analisar(sessao, empresa, usuario, conteudo)
    if analise.modelo is None or not analise.modelo.confirmado:
        if analise.modelo is None:  # a sugestão fica guardada: a tela de confirmação não pergunta à IA de novo
            sessao.add(
                ModeloPlanilha(
                    assinatura=analise.assinatura,
                    titulos=analise.titulos,
                    linha_titulos=analise.linha_titulos,
                    colunas=analise.colunas,
                    origem=analise.origem,
                    confirmado=False,
                )
            )
        arquivo = guardar_arquivo(sessao, empresa, "EXTRATO", nome, conteudo, usuario)
        raise PrecisaConfirmar(arquivo, "é a 1ª vez deste modelo de planilha — confira as colunas e a conta.")

    if conta is None and analise.banco_no_arquivo:
        conta = analise.banco_no_arquivo
    if conta is None:
        usadas = sessao.scalars(
            select(ContaBancaria).where(
                ContaBancaria.empresa_id == empresa.id, ContaBancaria.assinatura_planilha == analise.assinatura
            )
        ).all()
        if len(usadas) != 1:
            arquivo = guardar_arquivo(sessao, empresa, "EXTRATO", nome, conteudo, usuario)
            raise PrecisaConfirmar(arquivo, "a planilha não diz de qual conta bancária ela é — escolha a conta.")
        conta = usadas[0]

    montagem = montar(analise.linhas, analise.linha_titulos, analise.colunas)
    if not montagem.movimentos:
        raise ErroLeitura(f"Não encontrei movimentos na planilha “{nome}” com as colunas escolhidas.")
    if isinstance(conta, ContaBancaria):
        dados_conta = {
            "banco": conta.banco_codigo,
            "agencia": conta.agencia,
            "numero": conta.numero,
            "tipo": conta.tipo,
        }
    else:
        dados_conta = {"tipo": "BANCO", **conta}
    datas = [m.data for m in montagem.movimentos]
    inicio, fim = min(datas), max(datas)
    if (inicio.year, inicio.month) == (fim.year, fim.month):  # extrato de um mês: do dia 1º ao último
        inicio, fim = inicio.replace(day=1), fim.replace(day=calendar.monthrange(fim.year, fim.month)[1])
    return ExtratoLido(
        leitor="Planilha (Excel/CSV)",
        banco=dados_conta["banco"],
        agencia=dados_conta.get("agencia", ""),
        numero=dados_conta["numero"],
        tipo=dados_conta.get("tipo") or "BANCO",
        inicio=inicio,
        fim=fim,
        saldo_inicial=montagem.saldo_inicial,
        saldo_final=montagem.saldo_final,
        movimentos=montagem.movimentos,
        avisos=montagem.avisos,
        assinatura_planilha=analise.assinatura,
    )
