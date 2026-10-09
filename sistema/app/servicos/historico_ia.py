"""IA no histórico (§6.1, item 3): o que as regras não conseguem separar.

1. Lançamento com um lado só (Diário impresso só com algumas contas) fora do modelo do extrato:
   a IA diz se foi pagamento/recebimento pelo banco (o lado que falta é o banco) ou lançamento interno
   (provisão, nota fiscal a pagar, reconhecimento de receita).
2. Pagamento/recebimento com histórico fora do modelo “FAVORECIDO - NATUREZA - DOC”
   (ex.: “PAGTO SABESP REF CONTA AGUA”): a IA separa favorecido, CNPJ/CPF e natureza.

Históricos do mesmo modelo, na mesma conta e no mesmo lado vão numa pergunta só; cada lançamento
é perguntado uma vez (`revisado_ia`). A resposta é conferida antes de gravar: o CNPJ/CPF só vale
com dígito correto e se estiver escrito no histórico.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import IAIndisponivel, chamar_ia
from app.modelos import ContaContabil, Empresa, LancamentoHistorico, Usuario
from app.servicos.aprendizado import lado_da_contrapartida, normalizar_natureza
from app.servicos.contas_chave import naturezas, normalizar
from app.servicos.documentos import normalizar_documento, tipo_documento

TAMANHO_LOTE = 40
MAXIMO_DE_LOTES = 10  # por vez: um histórico enorme continua no próximo clique

INSTRUCOES = """Você é contador(a) do escritório Zera Contabilidade e ajuda o sistema ZERA CONTÁBIL MAX a \
aprender com os lançamentos antigos de uma empresa-cliente (exportados do Sistema Domínio). Cada item é um \
modelo de histórico, a conta onde foi lançado e o lado (débito ou crédito).

Para cada item responda:
- bancario: true se o lançamento foi um pagamento ou recebimento que passou pela conta do banco (o lado que \
não aparece é o banco): pagamento de fornecedor, salário, rescisão, guia de imposto; repasse ou doação \
recebida; rendimento de aplicação; tarifa. false se é lançamento contábil interno: provisão, apropriação da \
folha, valor a recolher retido do empregado, “aquisição conforme nota fiscal” (nota a pagar), reconhecimento \
de receita, transferência entre contas de resultado. Itens marcados “pelo banco” já são bancários: true.
- favorecido: quem recebeu (pagamento) ou quem pagou (recebimento) — pessoa, empresa ou órgão, como está \
no texto, em maiúsculas. Se o texto não diz quem é, use a origem como está escrita (ex.: REPASSE \
MUNICIPAL). Nunca invente nomes.
- cnpj_cpf: só os números do CNPJ ou CPF se estiverem escritos no histórico; senão "".
- natureza: o que foi pago ou recebido, curto e em maiúsculas (ex.: CONTA DE AGUA, SALARIO MENSAL, \
REPASSE MUNICIPAL), sem datas, meses, “REF” e números de documento.
Responda um item para cada id recebido."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "bancario": {"type": "boolean"},
                    "favorecido": {"type": "string"},
                    "cnpj_cpf": {"type": "string"},
                    "natureza": {"type": "string"},
                },
                "required": ["id", "bancario", "favorecido", "cnpj_cpf", "natureza"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["itens"],
    "additionalProperties": False,
}


def _consulta_pendentes(empresa: Empresa):
    um_lado = or_(LancamentoHistorico.conta_debito_id.is_(None), LancamentoHistorico.conta_credito_id.is_(None))
    return select(LancamentoHistorico).where(
        LancamentoHistorico.empresa_id == empresa.id,
        LancamentoHistorico.revisado_ia.is_(False),
        LancamentoHistorico.contrapartida_id.is_not(None),
        or_(
            and_(LancamentoHistorico.sentido == "OUTRO", um_lado),
            and_(
                LancamentoHistorico.sentido.in_(("SAIDA", "ENTRADA")),
                LancamentoHistorico.historico.not_like("% - %"),
            ),
        ),
    )


def contar_pendentes(sessao: Session, empresa: Empresa) -> int:
    return sessao.scalar(select(func.count()).select_from(_consulta_pendentes(empresa).subquery())) or 0


@dataclass
class Grupo:
    lancamentos: list[LancamentoHistorico]

    @property
    def exemplo(self) -> LancamentoHistorico:
        return max(self.lancamentos, key=lambda lancamento: (lancamento.data, lancamento.id))

    @property
    def decidir_banco(self) -> bool:
        return self.exemplo.sentido == "OUTRO"


def agrupar(lancamentos: list[LancamentoHistorico]) -> list[Grupo]:
    grupos: dict[tuple, list[LancamentoHistorico]] = defaultdict(list)
    for lancamento in lancamentos:
        modelo = normalizar_natureza(lancamento.historico) or normalizar(lancamento.historico)[:80]
        chave = (modelo, lancamento.contrapartida_id, lado_da_contrapartida(lancamento), lancamento.sentido == "OUTRO")
        grupos[chave].append(lancamento)
    return sorted((Grupo(itens) for itens in grupos.values()), key=lambda g: -len(g.lancamentos))


def _texto_item(numero: int, grupo: Grupo, contas: dict[int, ContaContabil], natureza: dict[int, str]) -> str:
    exemplo = grupo.exemplo
    conta = contas[exemplo.contrapartida_id]
    lado = "débito" if lado_da_contrapartida(exemplo) == "D" else "crédito"
    if grupo.decidir_banco:
        situacao = "o outro lado não está no arquivo"
    else:
        situacao = "pagamento pelo banco" if exemplo.sentido == "SAIDA" else "recebimento pelo banco"
    vezes = len(grupo.lancamentos)
    return (
        f"{numero}. conta {conta.classificacao_formatada} {conta.descricao} ({natureza.get(conta.id, '-')}) | "
        f"{lado} | {situacao} | {vezes} vez(es), ex.: R$ {exemplo.valor} em {exemplo.data:%d/%m/%Y} | "
        f"histórico: “{exemplo.historico}”"
    )


def _limpar(texto: object, tamanho: int = 200) -> str:
    return " ".join(str(texto or "").upper().split())[:tamanho]


def _documento_do_texto(resposta: object, historico: str) -> str | None:
    """Só aceita o CNPJ/CPF da IA se o dígito confere e os números estão no histórico."""
    documento = normalizar_documento(str(resposta or ""))
    if not documento or tipo_documento(documento) is None:
        return None
    return documento if documento in normalizar_documento(historico) else None


@dataclass
class ResultadoRevisao:
    grupos: int = 0
    revisados: int = 0  # lançamentos que a IA viu
    bancarios: int = 0  # um lado só que a IA disse que passou pelo banco (agora ensinam o extrato)
    separados: int = 0  # históricos fora do modelo com favorecido/natureza separados
    restantes: int = 0  # ficaram para a próxima vez (limite de lotes ou erro)
    aviso: str = ""

    def resumo(self) -> str:
        texto = f"🤖 A IA revisou {self.revisados} lançamento(s) do histórico"
        partes = []
        if self.bancarios:
            partes.append(f"{self.bancarios} eram pagamento/recebimento pelo banco")
        if self.separados:
            partes.append(f"{self.separados} tiveram favorecido e natureza separados")
        texto += (": " + " e ".join(partes)) if partes else ""
        if self.restantes:
            texto += f". Faltam {self.restantes}: clique em “Completar com a IA” de novo"
        return texto + "."


def revisar_historico(sessao: Session, empresa: Empresa, usuario: Usuario | None = None) -> ResultadoRevisao:
    """Pergunta à IA, em lotes, o que as regras não resolveram. IA desligada → IAIndisponivel (nada muda)."""
    resultado = ResultadoRevisao()
    grupos = agrupar(list(sessao.scalars(_consulta_pendentes(empresa))))
    if not grupos:
        return resultado
    lista_contas = list(sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)))
    contas = {conta.id: conta for conta in lista_contas}
    natureza = naturezas(lista_contas)
    contexto = f"Empresa: {empresa.nome}.\nPerfil: {empresa.perfil_ia or 'ainda não escrito'}"
    lotes = [grupos[i : i + TAMANHO_LOTE] for i in range(0, len(grupos), TAMANHO_LOTE)]
    for numero_lote, lote in enumerate(lotes[:MAXIMO_DE_LOTES]):
        pedido = PedidoIA(
            finalidade="historico_ia",
            instrucoes=INSTRUCOES,
            contexto=contexto,
            pergunta="\n".join(_texto_item(i, grupo, contas, natureza) for i, grupo in enumerate(lote, 1)),
            esquema=ESQUEMA,
            max_tokens=8000,
        )
        try:
            resposta = chamar_ia(sessao, pedido, empresa, usuario)
        except IAIndisponivel as erro:
            if numero_lote == 0:
                raise
            resultado.aviso = str(erro)
            break
        except ErroIA as erro:
            resultado.aviso = f"A IA não respondeu agora ({erro}). O que faltou fica para a próxima vez."
            break
        respondidos = {item.get("id"): item for item in resposta.dados.get("itens", []) if isinstance(item, dict)}
        for i, grupo in enumerate(lote, 1):
            if (item := respondidos.get(i)) is not None:
                _aplicar(grupo, item, resultado)
        sessao.flush()
    resultado.restantes = sum(len(g.lancamentos) for g in grupos if not all(lanc.revisado_ia for lanc in g.lancamentos))
    return resultado


def _aplicar(grupo: Grupo, item: dict, resultado: ResultadoRevisao) -> None:
    resultado.grupos += 1
    favorecido, natureza = _limpar(item.get("favorecido")), _limpar(item.get("natureza"))
    virou_bancario = grupo.decidir_banco and item.get("bancario") is True
    for lancamento in grupo.lancamentos:
        lancamento.revisado_ia = True
        resultado.revisados += 1
        if virou_bancario:
            lancamento.sentido = "SAIDA" if lado_da_contrapartida(lancamento) == "D" else "ENTRADA"
            resultado.bancarios += 1
        if lancamento.sentido == "OUTRO" or " - " in lancamento.historico:
            continue  # interno (não ensina o extrato) ou já separado pelas regras
        if favorecido:
            lancamento.favorecido = favorecido
        if natureza:
            lancamento.natureza = natureza
        if not lancamento.cnpj_cpf:
            lancamento.cnpj_cpf = _documento_do_texto(item.get("cnpj_cpf"), lancamento.historico)
        resultado.separados += not virou_bancario
