"""Auto-configuração das contas-chave pelo plano de contas (§3.2.1).

1º regras — palavras e números nas descrições das contas analíticas (rápido e sem custo);
2º IA (modelo forte) só para o que ficou incerto, escolhendo entre contas que existem;
3º conferência: a conta tem de existir, ser analítica e ter a natureza certa — senão não é aplicada;
4º o que ninguém achou vira um aviso para criar a conta no Domínio (e reimportar) ou escolher.
A escolha feita pelo usuário (origem USUARIO) nunca é sobrescrita.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import chamar_ia
from app.modelos import ContaChave, ContaContabil, Empresa, Usuario

CONFIANCA_ALTA = 80  # aplicada sem pedir conferência
CONFIANCA_MINIMA = 50  # abaixo disso a conta não é aplicada


def normalizar(texto: str | None) -> str:
    """Maiúsculas, sem acentos e sem espaços repetidos."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.upper().split())


# ---------------------------------------------------------------- natureza das contas


def natureza_do_grupo(descricao: str | None) -> str:
    texto = normalizar(descricao)
    if any(p in texto for p in ("COMPENSAC", "APURAC", "ENCERRAMENTO")):
        return "OUTRA"
    if "RECEITA" in texto:
        return "RECEITA"
    if "DESPESA" in texto or "CUSTO" in texto:
        return "DESPESA"
    if re.search(r"\bATIVO\b", texto):
        return "ATIVO"
    if "PASSIVO" in texto:
        return "PASSIVO"
    if "PATRIMONIO" in texto:
        return "PL"
    return "OUTRA"


def naturezas(contas: list[ContaContabil]) -> dict[int, str]:
    """Natureza de cada conta pelo nome do grupo de 1º nível (cada plano numera os grupos de um jeito:
    na Casa Criança 3 = despesas e 4 = receitas; em outros planos é o contrário)."""
    nivel1 = {c.classificacao: c.descricao for c in contas if c.nivel == 1}
    nivel2 = {c.classificacao: c.descricao for c in contas if c.nivel == 2}
    tamanho1 = min((len(c) for c in nivel1), default=1)
    tamanho2 = min((len(c) for c in nivel2), default=2)
    resultado = {}
    for conta in contas:
        natureza = natureza_do_grupo(nivel1.get(conta.classificacao[:tamanho1]))
        if natureza == "PASSIVO" and "PATRIMONIO" in normalizar(nivel2.get(conta.classificacao[:tamanho2])):
            natureza = "PL"
        resultado[conta.id] = natureza
    return resultado


# ---------------------------------------------------------------- tipos de conta-chave


@dataclass(frozen=True)
class TipoChave:
    nome: str  # como aparece na tela
    natureza: str  # ATIVO, PASSIVO, RECEITA ou DESPESA
    padroes: tuple[tuple[str, int], ...]  # (expressão na descrição normalizada, peso; peso negativo afasta)
    explicacao: str  # o que é, para a IA


TIPOS: dict[str, TipoChave] = {
    "RENDIMENTO": TipoChave(
        "Rendimentos de aplicação e poupança",
        "RECEITA",
        (
            (r"RENDIMENT", 3),
            (r"JUROS (DE|S/|SOBRE) APLICAC", 3),
            (r"RECEITAS? (C/|COM |DE )?APLICAC", 3),
            (r"RECEITAS? FINANCEIRAS?", 1),
            (r"A APLICAR", -3),
        ),
        "receita de juros, rendimentos e reajuste monetário de poupança e aplicações financeiras",
    ),
    "IR_RETIDO": TipoChave(
        "IR retido sobre aplicações",
        "ATIVO",
        (
            (r"IRRF A (RECUPERAR|COMPENSAR)", 3),
            (r"IMPOSTO DE RENDA (RETIDO|A RECUPERAR|A COMPENSAR)", 3),
            (r"\bIR(RF)? RETIDO", 2),
            (r"FOLHA|ALUGUE|S/ ?NF", -2),
        ),
        "imposto de renda retido na fonte sobre rendimentos de aplicação, a recuperar ou compensar",
    ),
    "TARIFA": TipoChave(
        "Tarifas bancárias",
        "DESPESA",
        (
            (r"TARIFA", 3),
            (r"DESPESAS? BANCARIA", 3),
            (r"SERVICOS? BANCARIOS", 2),
            (r"COMISSOES BANCARIAS", 1),
        ),
        "tarifas e taxas cobradas pelo banco (pacote de serviços, TED, emissão de boleto)",
    ),
    "IOF": TipoChave("IOF", "DESPESA", ((r"\bIOF\b", 3),), "IOF cobrado pelo banco"),
    "JUROS_PAGOS": TipoChave(
        "Juros e multas pagos",
        "DESPESA",
        (
            (r"JUROS (PASSIVOS|DE MORA|PAGOS)", 3),
            (r"MULTAS? E JUROS|JUROS E MULTAS?", 2),
            (r"ENCARGOS FINANCEIROS", 1),
            (r"CAPITAL PROPRIO|EMPRESTIMO|FINANCIAMENTO", -3),
        ),
        "juros e multas pagos por atraso de pagamento ou uso de cheque especial",
    ),
    "FORNECEDOR_GENERICO": TipoChave(
        "Fornecedores (conta geral)",
        "PASSIVO",
        ((r"^FORNECEDORES DIVERSOS$", 4), (r"^FORNECEDORES( NACIONAIS)?$", 3)),
        "conta geral de fornecedores a pagar, usada quando o fornecedor não tem conta própria",
    ),
    "CLIENTE_GENERICO": TipoChave(
        "Clientes (conta geral)",
        "ATIVO",
        ((r"^CLIENTES DIVERSOS$", 4), (r"^CLIENTES$", 3), (r"^DUPLICATAS A RECEBER$", 2)),
        "conta geral de clientes a receber",
    ),
    "SALARIOS": TipoChave(
        "Salários a pagar",
        "PASSIVO",
        ((r"SALARIOS? (E ORDENADOS )?A PAGAR", 3), (r"ORDENADOS A PAGAR", 3)),
        "salários e ordenados a pagar aos empregados",
    ),
    "FGTS": TipoChave(
        "FGTS a recolher",
        "PASSIVO",
        ((r"^FGTS A (RECOLHER|PAGAR)$", 4), (r"FGTS A (RECOLHER|PAGAR)", 2), (r"PROVIS", -3)),
        "FGTS da folha de pagamento a recolher",
    ),
    "INSS": TipoChave(
        "INSS a recolher (folha)",
        "PASSIVO",
        (
            (r"^INSS A RECOLHER$", 4),
            (r"INSS.*(RAT|PATRONAL|FOLHA).*A RECOLHER", 3),
            (r"INSS.*A RECOLHER", 2),
            (r"RETID|RECEITA BRUTA|PROVIS", -2),
        ),
        "INSS da folha de pagamento a recolher",
    ),
}

TIPOS_BANCARIOS = {
    "BANCO": ("Conta corrente", "ATIVO"),
    "POUPANCA": ("Poupança", "ATIVO"),
    "APLICACAO": ("Aplicação financeira", "ATIVO"),
}


def nome_do_tipo(tipo: str) -> str:
    if tipo in TIPOS:
        return TIPOS[tipo].nome
    return TIPOS_BANCARIOS.get(tipo, (tipo,))[0]


# ---------------------------------------------------------------- plano carregado


@dataclass
class PlanoCarregado:
    contas: list[ContaContabil]
    natureza: dict[int, str]
    analiticas: dict[int, ContaContabil]  # por reduzido

    def texto(self, conta: ContaContabil) -> str:
        return normalizar(conta.descricao)


def carregar_plano(sessao: Session, empresa: Empresa) -> PlanoCarregado:
    contas = list(
        sessao.scalars(
            select(ContaContabil)
            .where(ContaContabil.empresa_id == empresa.id, ContaContabil.ativa)
            .order_by(ContaContabil.classificacao, ContaContabil.reduzido)
        )
    )
    return PlanoCarregado(contas, naturezas(contas), {c.reduzido: c for c in contas if c.analitica})


# ---------------------------------------------------------------- regras


@dataclass
class Sugestao:
    tipo: str
    conta: ContaContabil | None
    origem: str
    confianca: int
    justificativa: str
    referencia: str = ""


def candidatos(plano: PlanoCarregado, tipo: TipoChave) -> list[tuple[ContaContabil, int]]:
    achados = []
    for conta in plano.analiticas.values():
        if plano.natureza.get(conta.id) != tipo.natureza:
            continue
        texto = plano.texto(conta)
        positivos = [peso for padrao, peso in tipo.padroes if peso > 0 and re.search(padrao, texto)]
        if not positivos:
            continue
        negativos = sum(peso for padrao, peso in tipo.padroes if peso < 0 and re.search(padrao, texto))
        peso = max(positivos) + negativos
        if peso > 0:
            achados.append((conta, peso))
    return sorted(achados, key=lambda item: (-item[1], item[0].classificacao, item[0].reduzido))


def _pela_regra(chave: str, achados: list[tuple[ContaContabil, int]]) -> Sugestao | None:
    """Uma conta claramente melhor que as outras → aplicada pela regra. Senão → None (fica para a IA)."""
    if not achados:
        return None
    melhor, peso = achados[0]
    if len(achados) > 1 and achados[1][1] == peso:
        return None
    confianca = 95 if len(achados) == 1 else 85
    return Sugestao(chave, melhor, "REGRA", confianca, f"Conta do plano com o nome “{melhor.descricao}”.")


def _reserva(chave: str, achados: list[tuple[ContaContabil, int]]) -> Sugestao:
    """Quando a IA não pôde ajudar: a primeira do plano entre as parecidas, para conferir."""
    if not achados:
        return Sugestao(chave, None, "REGRA", 0, "Não encontrei no plano uma conta para isto.")
    melhor = achados[0][0]
    outras = ", ".join(str(c.reduzido) for c, _ in achados[1:6]) + (" …" if len(achados) > 6 else "")
    return Sugestao(
        chave,
        melhor,
        "REGRA",
        60,
        f"Há {len(achados)} contas parecidas (também {outras}); escolhida a primeira do plano. Confira.",
    )


# ---------------------------------------------------------------- IA

INSTRUCOES = """Você é contador(a) especialista no Sistema Domínio e configura o sistema ZERA CONTÁBIL MAX \
para uma empresa-cliente do escritório. Você recebe o plano de contas completo da empresa (só as contas \
analíticas recebem lançamento) e escolhe, para cada finalidade pedida, a conta analítica que o escritório \
usaria ao lançar os movimentos do extrato bancário.

Regras:
- Responda somente com contas ANALÍTICAS que existem no plano, pelo código reduzido. Se nenhuma servir, \
responda conta_reduzida 0 — nunca invente.
- Respeite a natureza pedida (ATIVO, PASSIVO, RECEITA ou DESPESA).
- Quando houver contas parecidas em grupos diferentes (por programa, projeto ou convênio), prefira a do \
grupo administrativo/geral e diga isso na justificativa.
- confianca de 0 a 100: 90 ou mais só quando a conta é claramente a certa; 50 a 89 quando é provável mas \
há alternativas; abaixo de 50 quando é um palpite.
- justificativa: uma frase curta em português citando o código e o nome da conta escolhida."""


def contexto_do_plano(plano: PlanoCarregado, empresa: Empresa) -> str:
    publicos = empresa.dados_publicos or {}
    linhas = [
        f"EMPRESA: {empresa.nome} (código {empresa.codigo_dominio})",
        f"REGIME: {empresa.regime.rotulo if empresa.regime else 'não informado'}",
        f"NATUREZA JURÍDICA: {publicos.get('natureza_juridica', 'não informada')}",
        f"ATIVIDADE: {publicos.get('atividade', 'não informada')}",
        "",
        "PLANO DE CONTAS (reduzido | classificação | descrição | tipo | natureza):",
    ]
    for conta in plano.contas:
        tipo = "analítica" if conta.analitica else "grupo"
        natureza = plano.natureza.get(conta.id, "OUTRA")
        linhas.append(f"{conta.reduzido} | {conta.classificacao_formatada} | {conta.descricao} | {tipo} | {natureza}")
    return "\n".join(linhas)


def _esquema(tipos: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "contas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {"type": "string", "enum": tipos},
                        "conta_reduzida": {"type": "integer"},
                        "confianca": {"type": "integer"},
                        "justificativa": {"type": "string"},
                    },
                    "required": ["tipo", "conta_reduzida", "confianca", "justificativa"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["contas"],
        "additionalProperties": False,
    }


def conferir_resposta_ia(
    dados: dict[str, Any], naturezas_pedidas: dict[str, str], plano: PlanoCarregado, referencia: str = ""
) -> dict[str, Sugestao]:
    """A IA nunca grava sozinha: conta inexistente, sintética ou de natureza errada é recusada."""
    sugestoes = {}
    for item in dados.get("contas") or []:
        tipo = item.get("tipo")
        if tipo not in naturezas_pedidas or tipo in sugestoes:
            continue
        confianca = max(0, min(100, int(item.get("confianca") or 0)))
        justificativa = str(item.get("justificativa") or "").strip()[:500]
        reduzido = item.get("conta_reduzida") or 0
        conta = plano.analiticas.get(reduzido) if reduzido else None
        if reduzido and conta is None:
            conta, confianca = None, 0
            justificativa = f"A IA sugeriu a conta {reduzido}, que não existe como analítica no plano; não aplicada."
        elif conta is not None and plano.natureza.get(conta.id) != naturezas_pedidas[tipo]:
            justificativa = (
                f"A IA sugeriu {conta.rotulo}, mas ela é do {plano.natureza.get(conta.id)} "
                f"e precisava ser do {naturezas_pedidas[tipo]}; não aplicada."
            )
            conta, confianca = None, 0
        elif conta is not None and confianca < CONFIANCA_MINIMA:
            justificativa = f"Palpite fraco da IA ({confianca}%): {justificativa}"
            conta = None
        sugestoes[tipo] = Sugestao(tipo, conta, "IA", confianca, f"🤖 {justificativa}", referencia)
    return sugestoes


def _perguntar_ia(
    sessao: Session,
    empresa: Empresa,
    usuario: Usuario | None,
    plano: PlanoCarregado,
    pedidos: dict[str, tuple[str, str, list[tuple[ContaContabil, int]]]],
    referencia: str = "",
) -> dict[str, Sugestao]:
    """pedidos: tipo → (explicação, natureza, candidatas pela regra)."""
    linhas = ["Escolha a conta analítica para cada finalidade abaixo."]
    for tipo, (explicacao, natureza, achados) in pedidos.items():
        linhas.append(f"\n- tipo {tipo}: {explicacao} (natureza {natureza}).")
        if achados:
            linhas.append("  Contas parecidas achadas por palavra: " + "; ".join(c.rotulo for c, _ in achados[:8]))
        else:
            linhas.append("  Nenhuma conta achada por palavra: procure no plano inteiro.")
    pedido = PedidoIA(
        finalidade="auto_configuracao",
        instrucoes=INSTRUCOES,
        contexto=contexto_do_plano(plano, empresa),
        pergunta="\n".join(linhas),
        esquema=_esquema(list(pedidos)),
        forte=True,
        esforco="medium",
    )
    resposta = chamar_ia(sessao, pedido, empresa, usuario)
    return conferir_resposta_ia(resposta.dados, {t: p[1] for t, p in pedidos.items()}, plano, referencia)


# ---------------------------------------------------------------- conta individual por fornecedor

_GENERICO = re.compile(r"FORNECEDOR|DIVERSOS|NACIONAIS|ESTRANGEIROS|A PAGAR|ADIANTAMENTO|\bXXX\b")
MINIMO_FORNECEDORES_COM_NOME = 5


def detectar_conta_individual(plano: PlanoCarregado) -> tuple[bool, ContaContabil | None, int]:
    """Grupo de Fornecedores (passivo) com várias analíticas com nome de empresa → conta individual."""
    melhor: tuple[int, int, ContaContabil | None] = (0, 0, None)
    for grupo in plano.contas:
        if grupo.analitica or plano.natureza.get(grupo.id) != "PASSIVO":
            continue
        if "FORNECEDOR" not in plano.texto(grupo):
            continue
        com_nome = sum(
            1
            for conta in plano.analiticas.values()
            if conta.classificacao.startswith(grupo.classificacao)
            and conta.classificacao != grupo.classificacao
            and not _GENERICO.search(plano.texto(conta))
        )
        chave = (com_nome, len(grupo.classificacao), grupo)
        if chave[:2] > melhor[:2]:
            melhor = chave
    com_nome, _, grupo = melhor
    return com_nome >= MINIMO_FORNECEDORES_COM_NOME, grupo, com_nome


# ---------------------------------------------------------------- gravar e orquestrar


@dataclass
class ResultadoAutoConfig:
    chaves: list[ContaChave] = field(default_factory=list)
    aviso_ia: str | None = None  # por que a IA não ajudou (sem chave, limite, erro)
    ia_usada: bool = False

    @property
    def achadas(self) -> list[ContaChave]:
        return [c for c in self.chaves if c.conta_id and c.confianca >= CONFIANCA_ALTA]

    @property
    def conferir(self) -> list[ContaChave]:
        return [c for c in self.chaves if c.conta_id and c.confianca < CONFIANCA_ALTA]

    @property
    def nao_encontradas(self) -> list[ContaChave]:
        return [c for c in self.chaves if not c.conta_id]

    def resumo(self) -> str:
        partes = [f"{len(self.achadas)} achadas"]
        if self.conferir:
            partes.append(f"{len(self.conferir)} para conferir")
        if self.nao_encontradas:
            partes.append(f"{len(self.nao_encontradas)} não encontrada(s)")
        return "🤖 Contas-chave: " + ", ".join(partes) + "."


def gravar_sugestao(sessao: Session, empresa: Empresa, sugestao: Sugestao) -> ContaChave:
    chave = sessao.scalar(
        select(ContaChave).where(
            ContaChave.empresa_id == empresa.id,
            ContaChave.tipo == sugestao.tipo,
            ContaChave.referencia == sugestao.referencia,
        )
    )
    if chave is not None and chave.origem == "USUARIO":
        return chave  # escolha do usuário vale mais que a automática
    if chave is None:
        chave = ContaChave(empresa_id=empresa.id, tipo=sugestao.tipo, referencia=sugestao.referencia)
        sessao.add(chave)
    chave.conta_id = sugestao.conta.id if sugestao.conta else None
    chave.conta = sugestao.conta
    chave.origem = sugestao.origem
    chave.confianca = sugestao.confianca if sugestao.conta else 0
    chave.justificativa = sugestao.justificativa
    return chave


def _aplicar_conta_individual(empresa: Empresa, plano: PlanoCarregado) -> None:
    automaticos = list(empresa.campos_automaticos or [])
    if empresa.usa_conta_individual is not None and "usa_conta_individual" not in automaticos:
        return  # o usuário já decidiu
    individual, grupo, _ = detectar_conta_individual(plano)
    empresa.usa_conta_individual = individual
    empresa.grupo_fornecedores = grupo.classificacao_formatada if individual and grupo else None
    for campo in ("usa_conta_individual", "grupo_fornecedores"):
        if campo not in automaticos:
            automaticos.append(campo)
    empresa.campos_automaticos = automaticos


def auto_configurar(sessao: Session, empresa: Empresa, usuario: Usuario | None = None) -> ResultadoAutoConfig:
    """Roda sozinho depois de importar o plano. Regras primeiro; IA só para o que ficou incerto."""
    plano = carregar_plano(sessao, empresa)
    resultado = ResultadoAutoConfig()
    if not plano.analiticas:
        return resultado
    _aplicar_conta_individual(empresa, plano)

    escolhidas: dict[str, Sugestao] = {}
    incertas: dict[str, list[tuple[ContaContabil, int]]] = {}
    for chave, tipo in TIPOS.items():
        achados = candidatos(plano, tipo)
        if sugestao := _pela_regra(chave, achados):
            escolhidas[chave] = sugestao
        else:
            incertas[chave] = achados

    if incertas:
        pedidos = {t: (TIPOS[t].explicacao, TIPOS[t].natureza, achados) for t, achados in incertas.items()}
        try:
            escolhidas.update(_perguntar_ia(sessao, empresa, usuario, plano, pedidos))
            resultado.ia_usada = True
        except ErroIA as erro:
            resultado.aviso_ia = str(erro)
        for chave, achados in incertas.items():
            escolhidas.setdefault(chave, _reserva(chave, achados))

    resultado.chaves = [gravar_sugestao(sessao, empresa, escolhidas[chave]) for chave in TIPOS]
    sessao.flush()
    return resultado


# ---------------------------------------------------------------- contas bancárias

BANCOS = (
    ("001", "BB", "Banco do Brasil", r"\bBB\b|BANCO DO BRASIL|\bBCO\.? (DO )?BRASIL|\bB\.? ?BRASIL"),
    ("104", "CEF", "Caixa Econômica Federal", r"\bCEF\b|CAIXA ECON"),
    ("341", "ITAU", "Itaú", r"ITAU"),
    ("237", "BRADESCO", "Bradesco", r"BRADESCO"),
    ("033", "SANTANDER", "Santander", r"SANTANDER"),
    ("748", "SICREDI", "Sicredi", r"SICREDI"),
    ("756", "SICOOB", "Sicoob", r"SICOOB"),
    ("077", "INTER", "Banco Inter", r"\bINTER\b"),
    ("260", "NUBANK", "Nubank", r"NUBANK|NU PAGAMENTOS"),
    ("041", "BANRISUL", "Banrisul", r"BANRISUL"),
)
_PALAVRAS_TIPO = {
    "BANCO": r"\bC/?C\b|CONTA CORRENTE|MOVIMENTO",
    "POUPANCA": r"POUP",
    "APLICACAO": r"APLIC|INVEST|\bCDB\b|FUNDO|RENDA FIXA",
}


def identificar_banco(texto: str) -> tuple[str, str, str] | None:
    """'BB', '001', 'Banco do Brasil' → ('001', 'BB', 'Banco do Brasil')."""
    normal = normalizar(texto)
    digitos = re.sub(r"\D", "", normal)
    for codigo, sigla, nome, padrao in BANCOS:
        if (
            normal == sigla
            or (digitos and digitos.zfill(3) == codigo and normal.isdigit())
            or re.search(padrao, normal)
        ):
            return codigo, sigla, nome
    return None


def _numeros(texto: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d[\d.\-/]*\d|\d", texto)}


def pontuar_conta_bancaria(texto: str, banco: tuple[str, str, str] | None, numero: str, tipo: str) -> int:
    numero_completo = re.sub(r"\D", "", numero)
    sem_digito = re.sub(r"\D", "", re.split(r"[-/]", numero)[0]) if re.search(r"[-/]", numero) else ""
    pontos = 0
    if numero_completo and (numero_completo in _numeros(texto) or (sem_digito and sem_digito in _numeros(texto))):
        pontos += 60
    if banco:
        if re.search(_padrao_banco(banco[0]), texto):
            pontos += 20
        elif any(re.search(p, texto) for c, _, _, p in BANCOS if c != banco[0]):
            pontos -= 30  # a descrição é de outro banco
    if re.search(_PALAVRAS_TIPO[tipo], texto):
        pontos += 15
    conflitos = {"BANCO": ("POUPANCA", "APLICACAO"), "POUPANCA": ("BANCO",), "APLICACAO": ("BANCO",)}[tipo]
    if any(re.search(_PALAVRAS_TIPO[outro], texto) for outro in conflitos):
        pontos -= 40
    return pontos


def _padrao_banco(codigo: str) -> str:
    return next(p for c, _, _, p in BANCOS if c == codigo)


def referencia_bancaria(banco: tuple[str, str, str] | None, numero: str) -> str:
    """Banco + número da conta (sem agência): o histórico e o extrato caem na mesma conta-chave."""
    sigla = banco[1] if banco else "BANCO"
    return f"{sigla} conta {numero.strip()}"[:80]


def ligar_conta_bancaria(
    sessao: Session,
    empresa: Empresa,
    banco_texto: str,
    agencia: str,
    numero: str,
    tipo: str,
    usuario: Usuario | None = None,
) -> tuple[ContaChave, str | None]:
    """Acha a conta contábil de uma conta bancária (extrato BB 72637-0 → conta 8).
    Devolve (conta-chave gravada, aviso de por que a IA não ajudou, se for o caso)."""
    banco = identificar_banco(banco_texto)
    referencia = referencia_bancaria(banco, numero)
    plano = carregar_plano(sessao, empresa)
    natureza = TIPOS_BANCARIOS[tipo][1]
    achados = sorted(
        (
            (conta, pontuar_conta_bancaria(plano.texto(conta), banco, numero, tipo))
            for conta in plano.analiticas.values()
            if plano.natureza.get(conta.id) == natureza
        ),
        key=lambda item: (-item[1], item[0].classificacao),
    )
    achados = [(c, p) for c, p in achados if p > 0]
    nome_banco = banco[2] if banco else banco_texto
    descricao = f"{TIPOS_BANCARIOS[tipo][0].lower()} do {nome_banco} ag. {agencia} conta {numero}"

    aviso_ia = None
    melhor = achados[0] if achados else None
    unica = melhor and (len(achados) == 1 or achados[1][1] < melhor[1])
    if melhor and melhor[1] >= 60 and unica:
        sugestao = Sugestao(
            tipo,
            melhor[0],
            "REGRA",
            95 if melhor[1] >= 90 else 80,
            f"Descrição da conta “{melhor[0].descricao}” bate com a {descricao}.",
            referencia,
        )
    else:
        sugestao = None
        pedidos = {tipo: (f"a {descricao}", natureza, achados)}
        try:
            sugestao = _perguntar_ia(sessao, empresa, usuario, plano, pedidos, referencia).get(tipo)
        except ErroIA as erro:
            aviso_ia = str(erro)
        if sugestao is None or sugestao.conta is None:
            motivo = f" ({sugestao.justificativa})" if sugestao else ""
            sugestao = Sugestao(
                tipo,
                None,
                sugestao.origem if sugestao else "REGRA",
                0,
                f"Não encontrei no plano uma conta para a {descricao} — crie no Domínio e reimporte "
                f"o plano, ou escolha uma conta aqui.{motivo}",
                referencia,
            )
    chave = gravar_sugestao(sessao, empresa, sugestao)
    sessao.flush()
    return chave, aviso_ia


# ---------------------------------------------------------------- telas


def contas_chave_da_empresa(sessao: Session, empresa: Empresa) -> list[ContaChave]:
    ordem = {tipo: i for i, tipo in enumerate([*TIPOS_BANCARIOS, *TIPOS])}
    chaves = sessao.scalars(select(ContaChave).where(ContaChave.empresa_id == empresa.id)).all()
    return sorted(chaves, key=lambda c: (ordem.get(c.tipo, 99), c.referencia))


def achar_conta_analitica(sessao: Session, empresa_id: int, texto: str) -> tuple[ContaContabil | None, str | None]:
    """Conta digitada pelo usuário (“355 – ÁGUA E ESGOTO” ou só “355”) → (conta, None) ou (None, erro)."""
    numero = re.match(r"\s*(\d+)", texto or "")
    if not numero:
        return None, "Digite o código reduzido ou escolha a conta na lista (ex.: 355 – ÁGUA E ESGOTO)."
    conta = sessao.scalar(
        select(ContaContabil).where(
            ContaContabil.empresa_id == empresa_id,
            ContaContabil.reduzido == int(numero.group(1)),
            ContaContabil.ativa,
        )
    )
    if conta is None:
        return None, f"A conta {numero.group(1)} não existe no plano desta empresa."
    if not conta.analitica:
        return None, f"A conta {conta.rotulo} é sintética (grupo). Escolha uma conta analítica."
    return conta, None


def escolher_conta(sessao: Session, chave: ContaChave, texto: str, usuario: Usuario) -> str | None:
    """O usuário troca a conta de uma conta-chave. Devolve um erro em português ou None."""
    conta, erro = achar_conta_analitica(sessao, chave.empresa_id, texto)
    if erro:
        return erro
    chave.conta_id, chave.conta = conta.id, conta
    chave.origem, chave.confianca = "USUARIO", 100
    chave.justificativa = f"Escolhida por {usuario.nome}."
    return None
