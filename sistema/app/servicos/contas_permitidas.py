"""Quais contas o sistema pode sugerir para a empresa (pedidos de 15/10/2026).

1. Creches que dividem o código e o plano no Domínio (121: Carmem Dias, Jandira, Pastor Mario…): cada uma tem as
   suas contas, com o nome dela no fim (“SALÁRIO MENSAL - CARMEM DIAS”). O cadastro de uma creche só recebe sugestão
   de conta dela ou de conta comum (sem nome de creche). A conta de outra creche vira a “mesma” conta desta
   (“ENERGIA ELÉTRICA - JANDIRA” → “ENERGIA ELETRICA - CARMEM DIAS”); se ela não existir, a linha fica pendente.
   O Domínio corta a descrição em 40 letras: “ALIMENTAÇÃO DO TRABALHADOR - PASTOR MARI” também é da PASTOR MARIO.
2. Associação (terceiro setor): o pagamento vai direto para a conta de resultado (despesa), nunca para a conta do
   fornecedor. A despesa de cada fornecedor vem do histórico (a provisão: débito na despesa, crédito no fornecedor);
   sem histórico, a linha fica pendente para a IA ou o usuário escolherem a despesa.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import ContaContabil, Empresa, LancamentoHistorico
from app.servicos.contas_chave import naturezas, normalizar

MINIMO_CONTAS_DA_UNIDADE = 3  # um nome no fim de 3 contas ou mais (e que se repete com outra creche) é uma unidade
MINIMO_BASES_EM_COMUM = 2
SEMELHANCA_DA_BASE = 88
# palavras que fecham contas comuns e não são nome de creche (“INSS - EMPRESA”, “IRRF - TERCEIROS”)
_NAO_E_UNIDADE = re.compile(
    r"^(EMPRESA|EMPREGADOS?|FUNCIONARIOS?|SOCIOS?|TERCEIROS?|PJ|PF|RETIDOS?|A PAGAR|A RECOLHER|A RECEBER|MATRIZ|"
    r"FILIAL|DIVERSOS?|OUTROS?|OUTRAS|NACIONAIS|ESTRANGEIROS|CURTO PRAZO|LONGO PRAZO|C/C|CC)$"
)
_NOME_DE_EMPRESA = re.compile(
    r"\b(LTDA|S\s?/\s?A|S\.A|SA|EIRELI|ME|EPP|MEI|COMERCIO|COMERCIAL|DISTRIBUIDORA|INDUSTRIA|SUPERMERCADOS?|"
    r"DEDETIZADORA|LOJAS?|ATACADO|ATACADISTA)\b\.?"
)
_OBRIGACAO = re.compile(
    r"SALARI|ORDENAD|FERIAS|13|INSS|FGTS|IRRF|\bPIS\b|COFINS|CSLL|CSRF|\bISS|IMPOST|TRIBUT|RECOLHER|PROVIS|"
    r"EMPRESTIM|FINANCIAMENT|SUBVENC|CONVENIO|PARCELAMENT|RESCIS|PENSAO|SINDICA|CONTRIBUIC|CHEQUE"
)


def _base_e_nome(descricao: str | None) -> tuple[str, str]:
    """“SALÁRIO MENSAL - CARMEM DIAS” → (“SALARIO MENSAL”, “CARMEM DIAS”); sem “ - ” → (descrição, “”)."""
    partes = re.split(r"\s+-\s+", normalizar(descricao))
    if len(partes) < 2:
        return partes[0], ""
    return " - ".join(partes[:-1]), partes[-1]


def _mesma_base(a: str, b: str) -> int:
    return 100 if a == b else round(fuzz.ratio(a, b))


def unidades_do_plano(contas: list[ContaContabil]) -> list[str]:
    """Nomes de creche que fecham as contas do plano (“CARMEM DIAS”, “JANDIRA”…), já sem os cortes do Domínio."""
    bases: dict[str, set[str]] = defaultdict(set)
    for conta in contas:
        if not conta.analitica:
            continue
        base, nome = _base_e_nome(conta.descricao)
        if base and len(nome) >= 3 and not re.search(r"\d", nome) and not _NAO_E_UNIDADE.match(nome):
            bases[nome].add(base)
    completos: dict[str, set[str]] = {}
    # “PASTOR MARI” (cortado pelo Domínio), “PARAVATI” e “ROGERIO” (escritos curtos) juntam com o nome inteiro
    for nome in sorted(bases, key=lambda n: (len(n.split()), len(n)), reverse=True):
        dono = _unidade_que_casa(nome, list(completos))
        if dono:
            completos[dono] |= bases[nome]
        else:
            completos[nome] = set(bases[nome])
    candidatos = {n: b for n, b in completos.items() if len(b) >= MINIMO_CONTAS_DA_UNIDADE}

    def em_comum(a: set[str], b: set[str]) -> int:
        return sum(1 for x in a if any(_mesma_base(x, y) >= SEMELHANCA_DA_BASE for y in b))

    # creche de verdade divide as mesmas contas com outra (SALÁRIO MENSAL de cada uma)
    return sorted(
        n
        for n, b in candidatos.items()
        if any(em_comum(b, outra) >= MINIMO_BASES_EM_COMUM for m, outra in candidatos.items() if m != n)
    )


def _parte_de(nome: str, unidade: str) -> bool:
    """Cada palavra do nome é o começo de uma palavra da unidade: “CARMEM DIA” e “PARAVATI” são parte de “CARMEM
    DIAS” e “ROGERIO PARAVATI”."""
    palavras = unidade.split()
    return all(any(p.startswith(q) for p in palavras) for q in nome.split() if len(q) >= 3) and len(nome) >= 4


def _unidade_que_casa(nome: str, unidades: list[str]) -> str | None:
    nome = normalizar(nome)
    if not nome:
        return None
    if nome in unidades:
        return nome
    casam = [u for u in unidades if _parte_de(nome, u)]
    return casam[0] if len(casam) == 1 else None


def unidade_da_empresa(empresa: Empresa, unidades: list[str]) -> str:
    """A unidade escrita no cadastro, com o nome que está no plano. Não se adivinha pelo nome da empresa: na APAE
    as contas terminam com o nome do projeto (“- APAE”, “- ESTIMULANDO”) e quem decide é a conta do banco."""
    if not empresa.unidade:
        return ""
    return _unidade_que_casa(empresa.unidade, unidades) or normalizar(empresa.unidade)


# ---------------------------------------------------------------- fornecedores (terceiro setor)


def contas_de_fornecedor(contas: list[ContaContabil], empresa: Empresa) -> set[int]:
    """Contas de fornecedor do plano: no grupo de fornecedores (pelo nome do grupo ou o do cadastro) ou, sem
    grupo, no passivo com nome de empresa (“ADONAI DISTRIBUIDORA LTDA.”) e que não é obrigação (salário, imposto…)."""
    natureza = naturezas(contas)
    # a classificação sem pontos do grupo é o começo da das contas dele (a máscara do plano é uma só)
    grupos = [(c.classificacao, normalizar(c.descricao)) for c in contas if not c.analitica]
    grupo_cadastro = re.sub(r"\D", "", empresa.grupo_fornecedores or "")
    achadas = set()
    for conta in contas:
        if not conta.analitica or natureza.get(conta.id) != "PASSIVO":
            continue
        classificacao, descricao = conta.classificacao, normalizar(conta.descricao)
        ancestrais = [d for g, d in grupos if g != classificacao and classificacao.startswith(g)]
        if grupo_cadastro and classificacao.startswith(grupo_cadastro) and classificacao != grupo_cadastro:
            achadas.add(conta.id)
        elif any("FORNECEDOR" in d for d in ancestrais) or "FORNECEDOR" in descricao:
            achadas.add(conta.id)
        elif _NOME_DE_EMPRESA.search(descricao) and not _OBRIGACAO.search(" ".join([descricao, *ancestrais])):
            achadas.add(conta.id)
    return achadas


def despesa_de_cada_fornecedor(
    sessao: Session, empresa: Empresa, fornecedores: set[int], natureza: dict[int, str]
) -> dict[int, int]:
    """Fornecedor → a despesa onde as compras dele foram lançadas no histórico (a mais usada; empate = a recente)."""
    if not fornecedores:
        return {}
    usos: dict[int, Counter] = defaultdict(Counter)
    recente: dict[tuple[int, int], date] = {}
    linhas = sessao.execute(
        select(
            LancamentoHistorico.conta_credito_id, LancamentoHistorico.conta_debito_id, LancamentoHistorico.data
        ).where(
            LancamentoHistorico.empresa_id == empresa.id,
            LancamentoHistorico.conta_credito_id.in_(fornecedores),
            LancamentoHistorico.conta_debito_id.is_not(None),
        )
    )
    for fornecedor, despesa, quando in linhas:
        if natureza.get(despesa) != "DESPESA":
            continue
        usos[fornecedor][despesa] += 1
        recente[(fornecedor, despesa)] = max(quando, recente.get((fornecedor, despesa), date.min))
    return {
        fornecedor: max(contador, key=lambda d: (contador[d], recente[(fornecedor, d)]))
        for fornecedor, contador in usos.items()
    }


# ---------------------------------------------------------------- o filtro


@dataclass
class FiltroContas:
    empresa: Empresa
    contas: dict[int, ContaContabil]
    unidades: list[str] = field(default_factory=list)
    unidade: str = ""
    de_fornecedor: set[int] = field(default_factory=set)
    despesa_do_fornecedor: dict[int, int] = field(default_factory=dict)
    # a classificação pergunta as mesmas contas muitas vezes: as respostas ficam guardadas enquanto o filtro vive
    _dona: dict[int, str | None] = field(default_factory=dict, repr=False)
    _equivalente: dict[tuple[int, str], ContaContabil | None] = field(default_factory=dict, repr=False)

    def unidade_da_conta(self, conta: ContaContabil) -> str | None:
        if conta.id not in self._dona:
            _, nome = _base_e_nome(conta.descricao)
            self._dona[conta.id] = _unidade_que_casa(nome, self.unidades) if nome else None
        return self._dona[conta.id]

    def unidade_para(self, banco: ContaContabil | None = None) -> str:
        """A creche/projeto da linha: a do cadastro; senão a da conta contábil do banco (“BANCO DO BRASIL 79391-4 -
        ESTIMULANDO” → as contas do projeto ESTIMULANDO)."""
        if self.unidade:
            return self.unidade
        return (self.unidade_da_conta(banco) or "") if banco is not None else ""

    def equivalente(self, conta: ContaContabil, unidade: str) -> ContaContabil | None:
        """A mesma conta desta unidade (ou a comum, sem nome de creche)."""
        if (conta.id, unidade) not in self._equivalente:
            self._equivalente[(conta.id, unidade)] = self._procurar_equivalente(conta, unidade)
        return self._equivalente[(conta.id, unidade)]

    def _procurar_equivalente(self, conta: ContaContabil, unidade: str) -> ContaContabil | None:
        base, _ = _base_e_nome(conta.descricao)
        candidatas = []
        for outra in self.contas.values():
            if not outra.analitica or not outra.ativa or outra.id == conta.id:
                continue
            dona = self.unidade_da_conta(outra)
            if dona not in (unidade, None):
                continue
            outra_base = _base_e_nome(outra.descricao)[0] if dona else normalizar(outra.descricao)
            nota = _mesma_base(base, outra_base)
            if nota >= SEMELHANCA_DA_BASE:
                candidatas.append((nota, dona == unidade, -outra.reduzido, outra))
        return max(candidatas, key=lambda c: c[:3])[3] if candidatas else None

    def ajustar(
        self, conta: ContaContabil | None, banco: ContaContabil | None = None
    ) -> tuple[ContaContabil | None, str]:
        """A conta que pode ser usada no lugar desta (ou None) e uma nota para a justificativa (vazia = sem troca).
        `banco` é a conta contábil do banco da linha: sem unidade no cadastro, é ela que diz a unidade."""
        if conta is None:
            return None, ""
        notas = []
        if self.empresa.terceiro_setor and conta.id in self.de_fornecedor:
            despesa = self.contas.get(self.despesa_do_fornecedor.get(conta.id, 0))
            if despesa is None:
                return None, (
                    f"Associação (terceiro setor): o pagamento vai para a conta de despesa, não para a do fornecedor "
                    f"{conta.rotulo} — escolha a despesa."
                )
            notas.append(f"associação: despesa {despesa.rotulo} no lugar da conta do fornecedor {conta.rotulo}")
            conta = despesa
        unidade = self.unidade_para(banco)
        dona = self.unidade_da_conta(conta) if unidade else None
        if dona and dona != unidade:
            if (equivalente := self.equivalente(conta, unidade)) is None:
                return None, (
                    f"A conta {conta.rotulo} é da unidade {dona}; não achei a mesma conta da {unidade} no plano "
                    "— escolha a conta (ou crie no Domínio e reimporte o plano)."
                )
            notas.append(f"a conta da unidade {dona} virou a da {unidade}: {equivalente.rotulo}")
            conta = equivalente
        if not notas:
            return conta, ""
        texto = "; ".join(notas)
        return conta, texto[0].upper() + texto[1:] + "."

    def permitida(self, conta: ContaContabil) -> bool:
        return self.ajustar(conta)[0] is conta


def carregar_filtro(sessao: Session, empresa: Empresa, contas: list[ContaContabil] | None = None) -> FiltroContas:
    if contas is None:
        contas = list(sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)))
    unidades = unidades_do_plano(contas)
    unidade = unidade_da_empresa(empresa, unidades)
    if unidade and unidade not in unidades:  # creche com poucas contas próprias ainda: as dela também contam
        unidades.append(unidade)
    filtro = FiltroContas(empresa, {c.id: c for c in contas}, unidades, unidade)
    if empresa.terceiro_setor:
        filtro.de_fornecedor = contas_de_fornecedor(contas, empresa)
        filtro.despesa_do_fornecedor = despesa_de_cada_fornecedor(
            sessao, empresa, filtro.de_fornecedor, naturezas(contas)
        )
    return filtro


# ---------------------------------------------------------------- conta do banco da creche


def contas_de_banco_da_unidade(sessao: Session, empresa: Empresa, filtro: FiltroContas) -> Counter:
    """Contas do Ativo onde caem os pagamentos e os repasses das contas da creche no histórico (a Carmem Dias paga
    tudo e recebe a subvenção na 1012; a Jandira na 7040)."""
    contagem: Counter = Counter()
    if not filtro.unidade:
        return contagem
    natureza = naturezas(list(filtro.contas.values()))
    linhas = sessao.execute(
        select(LancamentoHistorico.conta_debito_id, LancamentoHistorico.conta_credito_id).where(
            LancamentoHistorico.empresa_id == empresa.id, LancamentoHistorico.sentido.in_(("SAIDA", "ENTRADA"))
        )
    )
    for debito_id, credito_id in linhas:
        debito, credito = filtro.contas.get(debito_id), filtro.contas.get(credito_id)
        if debito is None or credito is None:
            continue
        if filtro.unidade_da_conta(debito) == filtro.unidade and natureza.get(credito.id) == "ATIVO":
            contagem[credito.id] += 1
        elif filtro.unidade_da_conta(credito) == filtro.unidade and natureza.get(debito.id) == "ATIVO":
            contagem[debito.id] += 1
    return contagem


def ligar_contas_da_unidade(sessao: Session, empresa: Empresa) -> int:
    """Todas as contas bancárias da creche (ao salvar a unidade no cadastro e no “Classificar de novo”)."""
    from app.modelos import ContaBancaria

    contas = sessao.scalars(select(ContaBancaria).where(ContaBancaria.empresa_id == empresa.id)).all()
    return sum(ligar_pela_unidade(sessao, empresa, conta.conta_chave) for conta in contas)


def ligar_pela_unidade(sessao: Session, empresa: Empresa, chave) -> bool:
    """Conta corrente ou poupança de creche sem conta contábil (ou com uma que a creche nunca usou): vale a conta do
    banco que o histórico dela usa — o escritório lança a conta corrente e a poupança da creche numa conta só, e
    as aplicações/resgates automáticos entre elas não geram lançamento. A escolha do usuário nunca é trocada."""
    if chave is None or chave.origem == "USUARIO" or not empresa.unidade:
        return False
    filtro = carregar_filtro(sessao, empresa)
    contagem = contas_de_banco_da_unidade(sessao, empresa, filtro)
    if not contagem or (chave.conta_id and chave.conta_id in contagem):
        return False
    conta_id, vezes = contagem.most_common(1)[0]
    if vezes < 5 or vezes / sum(contagem.values()) < 0.8:
        return False
    conta = filtro.contas[conta_id]
    chave.conta_id, chave.conta, chave.origem, chave.confianca = conta.id, conta, "REGRA", 90
    chave.justificativa = (
        f"Pelo histórico da creche {filtro.unidade}: os pagamentos e os repasses dela caem na conta {conta.rotulo} "
        f"({vezes} lançamentos)."
    )
    return True
