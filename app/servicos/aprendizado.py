"""Aprendizado com os lançamentos que o escritório já fez (§3.3, §6.1).

Fontes: lanctos.txt antigos (§11.5) e o Diário do Domínio em Excel (§11.3). Cada lançamento vira um
LancamentoHistorico (o mesmo lançamento vindo dos dois arquivos conta uma vez só) e `aprender`
recalcula os padrões da empresa.

- Favorecido → conta: vale o uso MAIS RECENTE (em 2025 os salários iam para a 331; em 2026, para a 187).
- Mesmo favorecido em contas diferentes explicadas pela natureza (sindicato: contribuição, mensalidade,
  plano odontológico) não é ambíguo: guarda a conta e os valores de cada natureza.
- Ambíguo = contas diferentes sem explicação → o usuário escolhe.
- Palavra-chave = natureza usada por vários favorecidos sempre na mesma conta (“SALARIO MENSAL” → 187).
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.ia.cliente import ErroIA, PedidoIA
from app.ia.servico import chamar_ia
from app.modelos import (
    ContaChave,
    ContaContabil,
    Empresa,
    Importacao,
    LancamentoHistorico,
    Padrao,
    Usuario,
)
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.contas_chave import (
    TIPOS_BANCARIOS,
    Sugestao,
    gravar_sugestao,
    identificar_banco,
    naturezas,
    normalizar,
    referencia_bancaria,
)
from app.servicos.diario import DiarioLido, eh_planilha, ler_diario
from app.servicos.documentos import formatar_documento, normalizar_documento, tipo_documento
from app.servicos.lanctos import ler_lanctos, parece_lanctos
from app.servicos.plano import Aviso, ErroLeitura, decodificar

# ---------------------------------------------------------------- textos

_LIGACOES = {"DE", "DA", "DO", "DOS", "DAS", "E"}
_SUFIXOS = {"LTDA", "ME", "EPP", "EIRELI", "SA", "MEI", "CIA", "SS"}
_MESES = {
    "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO",
    "NOVEMBRO", "DEZEMBRO", "JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ",
}  # fmt: skip
CNPJ_NO_TEXTO = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{3,4}\s*-?\s*\d{2}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


def normalizar_nome(texto: str | None) -> str:
    """'DANIELA CORDEIRO DE OLIVEIRA' e 'Daniela Cordeiro Oliveira' → 'DANIELA CORDEIRO OLIVEIRA'."""
    palavras = re.sub(r"[^A-Z0-9 ]", " ", normalizar(texto)).split()
    return " ".join(p for p in palavras if len(p) > 1 and not p.isdigit() and p not in _LIGACOES and p not in _SUFIXOS)[
        :200
    ]


def normalizar_natureza(texto: str | None) -> str:
    """'SALÁRIO MENSAL REF JANEIRO' → 'SALARIO MENSAL'; 'SERVIÇOS CONTABEIS (JUNHO)' → 'SERVICOS CONTABEIS'."""
    texto = re.sub(r"\bREF\b.*$", "", normalizar(texto))
    palavras = re.sub(r"[^A-Z0-9 ]", " ", texto).split()
    return " ".join(
        p for p in palavras if len(p) > 1 and not any(c.isdigit() for c in p) and p not in _LIGACOES | _MESES
    )[:200]


_MES_ENTRE_PARENTESES = re.compile(
    r"\s*\((?:JANEIRO|FEVEREIRO|MAR[CÇ]O|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO)[^)]*\)",
    re.IGNORECASE,
)


def natureza_para_exibir(texto: str | None) -> str | None:
    """'SERVIÇOS CONTABEIS (JUNHO)' → 'SERVIÇOS CONTABEIS'; 'SALÁRIO MENSAL REF JANEIRO' → 'SALÁRIO MENSAL'."""
    if not texto:
        return texto
    limpo = _MES_ENTRE_PARENTESES.sub("", re.sub(r"\s+REF\b.*$", "", texto, flags=re.IGNORECASE))
    return " ".join(limpo.split()) or texto


@dataclass
class Complemento:
    favorecido: str
    cnpj_cpf: str | None  # só quando o dígito confere
    natureza: str
    documento: str


def separar_complemento(texto: str) -> Complemento:
    """'SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N' → favorecido, CNPJ, natureza e documento."""
    partes = [parte.strip() for parte in texto.split(" - ")]
    documento = ""
    if len(partes) > 1 and re.fullmatch(r"S/?N|[\dA-Z./-]{1,30}", partes[-1].upper()):
        if re.search(r"\d|S/?N", partes[-1].upper()):
            documento = partes.pop()
    achados = [m.group(0) for m in CNPJ_NO_TEXTO.finditer(texto)]
    cnpj = next((normalizar_documento(a) for a in achados if tipo_documento(a)), None)
    limpas = [" ".join(CNPJ_NO_TEXTO.sub(" ", parte).split()).strip(" -") for parte in partes]
    limpas = [parte for parte in limpas if parte]
    return Complemento(
        favorecido=limpas[0] if limpas else "",
        cnpj_cpf=cnpj,
        natureza=" - ".join(limpas[1:]),
        documento=documento,
    )


# ---------------------------------------------------------------- contas de banco

_DISPONIVEL = re.compile(r"DISPONI|CAIXA E EQUIVALENTES")


def contas_de_banco(contas: list[ContaContabil], chaves: list[ContaChave]) -> set[int]:
    """Contas-chave bancárias + analíticas do grupo Disponível (caixa, bancos, aplicações)."""
    ids = {c.conta_id for c in chaves if c.tipo in TIPOS_BANCARIOS and c.conta_id}
    grupos = [c.classificacao for c in contas if not c.analitica and _DISPONIVEL.search(normalizar(c.descricao))]
    for conta in contas:
        if conta.analitica and any(conta.classificacao.startswith(g) for g in grupos):
            ids.add(conta.id)
    return ids


# ---------------------------------------------------------------- importação do histórico


@dataclass
class Movimento:
    """Um lançamento lido de qualquer formato, já com as contas do plano (no Diário filtrado falta um lado)."""

    numero: int  # linha no arquivo, para os avisos
    data: date
    debito: ContaContabil | None
    credito: ContaContabil | None
    valor: Decimal
    historico: str


@dataclass
class Leitura:
    formato: str
    movimentos: list[Movimento]
    avisos: list[Aviso]
    resumo: dict[str, Any]  # o que cada formato conta a mais (linhas, empresa, período...)


def _ler_lanctos(empresa: Empresa, conteudo: bytes, contas: list[ContaContabil]) -> Leitura:
    texto = decodificar(conteudo)
    if not parece_lanctos(texto):
        raise ErroLeitura(
            "Não reconheci o arquivo. Envie o lanctos.txt (o arquivo que a planilha gera para o Domínio) "
            "ou o Diário do Domínio em Excel (.xls ou .xlsx)."
        )
    linhas, avisos = ler_lanctos(texto)
    codigos = Counter(linha.codigo_empresa for linha in linhas if linha.codigo_empresa)
    if codigos and empresa.codigo_dominio not in codigos:
        outro = codigos.most_common(1)[0][0]
        raise ErroLeitura(
            f"Este arquivo é da empresa de código {outro} no Domínio, e esta é a {empresa.codigo_dominio}. "
            "Confira se escolheu a empresa certa."
        )
    de_outra = [linha for linha in linhas if linha.codigo_empresa not in (None, empresa.codigo_dominio)]
    if de_outra:
        avisos.append(
            Aviso(
                f"{len(de_outra)} linha(s) de outra empresa foram ignoradas.",
                [f"Linha {linha.numero}: código {linha.codigo_empresa}" for linha in de_outra],
            )
        )
    por_reduzido = {c.reduzido: c for c in contas}
    movimentos, sem_conta = [], []
    for linha in linhas:
        if linha in de_outra:
            continue
        debito, credito = por_reduzido.get(linha.debito), por_reduzido.get(linha.credito)
        if debito is None or credito is None:
            faltando = linha.debito if debito is None else linha.credito
            sem_conta.append(f"Linha {linha.numero}: conta {faltando} não existe no plano")
            continue
        movimentos.append(Movimento(linha.numero, linha.data, debito, credito, linha.valor, linha.complemento))
    if sem_conta:
        avisos.insert(
            0,
            Aviso(
                f"{len(sem_conta)} linha(s) com conta que não existe no plano ficaram de fora. "
                "Reimporte o plano se criou contas novas no Domínio.",
                sem_conta,
            ),
        )
    return Leitura("lanctos.txt", movimentos, avisos, {"linhas": len(linhas)})


def conta_pela_classificacao(candidatas: list[ContaContabil], descricao: str) -> ContaContabil | None:
    """Classificação → conta. Quando o plano repete a classificação (492 VALE TRANSPORTE e 10585 DESPESA COM
    RESCISÃO = 3.2.2.01.000010), decide pela descrição — que no plano do Domínio vem cortada em 40 letras."""
    analiticas = [c for c in candidatas if c.analitica] or candidatas
    if len(analiticas) <= 1:
        return analiticas[0] if analiticas else None
    texto = normalizar(descricao)
    iguais = [c for c in analiticas if normalizar(c.descricao) == texto]
    if len(iguais) == 1:
        return iguais[0]
    parecidas = [
        c for c in analiticas if texto and normalizar(c.descricao) and texto.startswith(normalizar(c.descricao))
    ]
    return parecidas[0] if len(parecidas) == 1 else None


def _conferir_empresa(sessao: Session, empresa: Empresa, lido: DiarioLido) -> list[str]:
    """O Diário traz o nome e o CNPJ da empresa: confere (arquivo de outra empresa é recusado)
    e preenche o que estiver vazio no cadastro, com o selo 🤖."""
    preenchidos = []
    if lido.cnpj and empresa.cnpj_cpf and empresa.cnpj_cpf != lido.cnpj:
        raise ErroLeitura(
            f"Este Diário é de {lido.empresa or 'outra empresa'} (CNPJ {formatar_documento(lido.cnpj)}), e a "
            f"empresa escolhida tem o CNPJ {formatar_documento(empresa.cnpj_cpf)}. Confira se escolheu a empresa certa."
        )
    if lido.cnpj and not empresa.cnpj_cpf:
        outra = sessao.scalar(select(Empresa).where(Empresa.cnpj_cpf == lido.cnpj, Empresa.id != empresa.id))
        if outra:
            raise ErroLeitura(
                f"Este Diário é do CNPJ {formatar_documento(lido.cnpj)}, que está cadastrado na empresa "
                f"{outra.nome} (código {outra.codigo_dominio}). Confira se escolheu a empresa certa."
            )
        empresa.cnpj_cpf = lido.cnpj
        preenchidos.append("cnpj_cpf")
    if lido.empresa and not empresa.razao_social:
        empresa.razao_social = lido.empresa[:200]
        preenchidos.append("razao_social")
    if preenchidos:
        automaticos = list(empresa.campos_automaticos or [])
        empresa.campos_automaticos = automaticos + [c for c in preenchidos if c not in automaticos]
    return preenchidos


def _ler_diario(sessao: Session, empresa: Empresa, conteudo: bytes, contas: list[ContaContabil]) -> Leitura:
    lido = ler_diario(conteudo)
    preenchidos = _conferir_empresa(sessao, empresa, lido)
    por_classificacao: dict[str, list[ContaContabil]] = defaultdict(list)
    for conta in contas:
        por_classificacao[conta.classificacao].append(conta)
    movimentos, sem_conta, duvidas = [], [], []
    for partida in lido.partidas:
        lados = []
        for linha in (partida.debito, partida.credito):
            if linha is None:
                lados.append(None)
                continue
            candidatas = por_classificacao.get(linha.classificacao, [])
            conta = conta_pela_classificacao(candidatas, linha.descricao)
            if conta is None:
                destino = duvidas if candidatas else sem_conta
                destino.append(f"Linha {linha.numero}: {linha.classificacao} {linha.descricao}")
                break
            lados.append(conta)
        else:
            movimentos.append(
                Movimento(partida.numero, partida.data, lados[0], lados[1], partida.valor, partida.historico)
            )
    avisos = list(lido.avisos)
    if duvidas:
        avisos.insert(
            0,
            Aviso(
                f"{len(duvidas)} lançamento(s) ficaram de fora: a classificação é de mais de uma conta no plano "
                "e a descrição não decidiu qual.",
                duvidas,
            ),
        )
    if sem_conta:
        avisos.insert(
            0,
            Aviso(
                f"{len(sem_conta)} lançamento(s) com classificação que não existe no plano ficaram de fora. "
                "Reimporte o plano se criou contas novas no Domínio.",
                sem_conta,
            ),
        )
    resumo = {
        "linhas": len(lido.linhas),
        "completo": lido.completo,
        "um_lado": lido.um_lado,
        "empresa": lido.empresa,
        "periodo": lido.periodo,
        "preenchidos": preenchidos,
    }
    return Leitura("Diário", movimentos, avisos, resumo)


def _parece_do_extrato(historico: str) -> bool:
    """Histórico no modelo do escritório para os lançamentos do extrato: “FAVORECIDO - NATUREZA - DOC”."""
    partes = separar_complemento(historico)
    return " - " in historico and bool(partes.favorecido) and bool(partes.natureza or partes.cnpj_cpf)


def _sentido(movimento: Movimento, bancos: set[int]) -> tuple[str, ContaContabil | None]:
    """SAIDA (pagou pelo banco), ENTRADA (recebeu) ou OUTRO, e a contrapartida (o lado que não é banco)."""
    debito, credito = movimento.debito, movimento.credito
    if debito and credito:
        if credito.id in bancos and debito.id not in bancos:
            return "SAIDA", debito
        if debito.id in bancos and credito.id not in bancos:
            return "ENTRADA", credito
        return "OUTRO", None
    visivel = debito or credito
    if visivel.id in bancos:
        return "OUTRO", None  # só o lado do banco: não dá para saber a contrapartida
    # o outro lado não veio no arquivo: histórico no modelo do extrato = pagamento ou recebimento pelo banco
    if _parece_do_extrato(movimento.historico):
        return ("SAIDA" if debito else "ENTRADA"), visivel
    return "OUTRO", visivel  # provisão, nota fiscal a pagar... fica guardado, mas não ensina o extrato


def _lados(data: date, valor: Decimal, historico: str, debito_id: int | None, credito_id: int | None) -> list[tuple]:
    texto = normalizar(historico)
    return [(lado, data, valor, texto, conta) for lado, conta in (("D", debito_id), ("C", credito_id)) if conta]


class _JaImportados:
    """Lançamentos que a empresa já tem, procurados por lado (data, valor, histórico, débito ou crédito, conta):
    o mesmo pagamento no lanctos.txt e no Diário do mesmo mês conta uma vez só."""

    def __init__(self, existentes: list[LancamentoHistorico]):
        self.por_lado: dict[tuple, list[LancamentoHistorico]] = defaultdict(list)
        for lancamento in existentes:
            for lado in self._lados_de(lancamento):
                self.por_lado[lado].append(lancamento)

    @staticmethod
    def _lados_de(lancamento: LancamentoHistorico) -> list[tuple]:
        return _lados(
            lancamento.data,
            lancamento.valor,
            lancamento.historico,
            lancamento.conta_debito_id,
            lancamento.conta_credito_id,
        )

    def tirar(self, movimento: Movimento) -> LancamentoHistorico | None:
        debito, credito = movimento.debito, movimento.credito
        lados = _lados(
            movimento.data,
            movimento.valor,
            movimento.historico,
            debito.id if debito else None,
            credito.id if credito else None,
        )
        for lado in lados:
            if self.por_lado.get(lado):
                achado = self.por_lado[lado][0]
                for outro in self._lados_de(achado):
                    self.por_lado[outro].remove(achado)
                return achado
        return None


def importar_historico(
    sessao: Session, empresa: Empresa, nome_arquivo: str, conteudo: bytes, usuario: Usuario | None
) -> Importacao:
    """lanctos.txt antigo ou Diário do Domínio (Excel) → LancamentoHistorico. Reimportar não duplica."""
    contas = list(sessao.scalars(select(ContaContabil).where(ContaContabil.empresa_id == empresa.id)))
    if not any(c.ativa for c in contas):
        raise ErroLeitura("Importe o plano de contas da empresa antes do histórico (aba 2 Plano de Contas).")
    if eh_planilha(conteudo):
        leitura = _ler_diario(sessao, empresa, conteudo, contas)
    else:
        leitura = _ler_lanctos(empresa, conteudo, contas)

    chaves = list(sessao.scalars(select(ContaChave).where(ContaChave.empresa_id == empresa.id)))
    bancos = contas_de_banco(contas, chaves)
    # reforço: conta do ATIVO presente em metade dos lançamentos é o banco (ex.: crédito 8 em todas)
    completos = [m for m in leitura.movimentos if m.debito and m.credito]
    uso = Counter(conta.id for m in completos for conta in (m.debito, m.credito))
    natureza = naturezas(contas)
    for conta_id, vezes in uso.items():
        if vezes >= len(completos) / 2 and natureza.get(conta_id) == "ATIVO":
            bancos.add(conta_id)

    arquivo = guardar_arquivo(sessao, empresa, "HISTORICO", nome_arquivo, conteudo, usuario)
    importacao = Importacao(
        empresa_id=empresa.id,
        tipo="HISTORICO",
        arquivo_id=arquivo.id,
        usuario_id=usuario.id if usuario else None,
    )
    sessao.add(importacao)
    sessao.flush()

    datas_lidas = [m.data for m in leitura.movimentos]
    existentes = (
        list(
            sessao.scalars(
                select(LancamentoHistorico).where(
                    LancamentoHistorico.empresa_id == empresa.id,
                    LancamentoHistorico.data.between(min(datas_lidas), max(datas_lidas)),
                )
            )
        )
        if datas_lidas
        else []
    )
    ja_importados = _JaImportados(existentes)
    marcas = set(sessao.scalars(select(LancamentoHistorico.marca).where(LancamentoHistorico.empresa_id == empresa.id)))
    novos, repetidos, completados = [], 0, 0
    for movimento in leitura.movimentos:
        sentido, contrapartida = _sentido(movimento, bancos)
        if (achado := ja_importados.tirar(movimento)) is not None:
            faltava_lado = achado.conta_debito_id is None or achado.conta_credito_id is None
            if movimento.debito and movimento.credito and faltava_lado:
                # o Diário filtrado trouxe um lado só; o lanctos.txt completa o lançamento
                achado.conta_debito_id, achado.conta_credito_id = movimento.debito.id, movimento.credito.id
                achado.sentido = sentido
                achado.contrapartida_id = contrapartida.id if contrapartida else None
                completados += 1
            else:
                repetidos += 1
            continue
        debito, credito = movimento.debito, movimento.credito
        base = (
            f"{movimento.data.isoformat()}|{debito.reduzido if debito else ''}|{credito.reduzido if credito else ''}"
            f"|{movimento.valor}|{normalizar(movimento.historico)}"
        )
        vez = 1
        while (marca := hashlib.sha256(f"{base}#{vez}".encode()).hexdigest()) in marcas:
            vez += 1  # duas linhas iguais no mesmo arquivo são dois lançamentos
        marcas.add(marca)
        partes = separar_complemento(movimento.historico)
        novos.append(
            LancamentoHistorico(
                empresa_id=empresa.id,
                importacao_id=importacao.id,
                data=movimento.data,
                conta_debito_id=debito.id if debito else None,
                conta_credito_id=credito.id if credito else None,
                valor=movimento.valor,
                historico=movimento.historico,
                favorecido=partes.favorecido[:200] or None,
                cnpj_cpf=partes.cnpj_cpf,
                natureza=partes.natureza[:200] or None,
                documento=partes.documento[:60] or None,
                sentido=sentido,
                contrapartida_id=contrapartida.id if contrapartida else None,
                marca=marca,
            )
        )
    sessao.add_all(novos)
    datas = [lancamento.data for lancamento in novos]
    importacao.resumo = {
        "formato": leitura.formato,
        **leitura.resumo,
        "novos": len(novos),
        "repetidos": repetidos,
        "completados": completados,
        "de": min(datas).isoformat() if datas else None,
        "ate": max(datas).isoformat() if datas else None,
    }
    importacao.avisos = [asdict(aviso) for aviso in leitura.avisos]
    registrar_evento(
        sessao,
        "IMPORTAR_HISTORICO",
        detalhe=f"{empresa.nome}: {leitura.formato} — {len(novos)} lançamentos novos, {repetidos} repetidos ignorados"
        + (f", {completados} completados" if completados else ""),
    )
    sessao.flush()
    _ligar_bancos_do_historico(sessao, empresa, bancos, contas)
    return importacao


def _ligar_bancos_do_historico(sessao: Session, empresa: Empresa, bancos: set[int], contas: list) -> None:
    """Conta usada como banco no histórico e com banco + número na descrição vira conta-chave bancária
    (“BCO BRASIL CC 72637-0” → BB conta 72637-0 → conta 8)."""
    uso = dict(
        sessao.execute(
            select(LancamentoHistorico.conta_credito_id, func.count())
            .where(LancamentoHistorico.empresa_id == empresa.id, LancamentoHistorico.sentido == "SAIDA")
            .group_by(LancamentoHistorico.conta_credito_id)
        ).all()
    )
    for conta_id, vezes in uso.items():
        conta = next((c for c in contas if c.id == conta_id), None)
        if conta is None or conta_id not in bancos:
            continue
        texto = normalizar(conta.descricao)
        banco = identificar_banco(texto)
        numero = re.search(r"\d[\d.]*-[\dXx]|\d{4,}", texto)
        if not banco or not numero:
            continue
        tipo = "POUPANCA" if "POUP" in texto else "APLICACAO" if "APLIC" in texto else "BANCO"
        gravar_sugestao(
            sessao,
            empresa,
            Sugestao(
                tipo,
                conta,
                "REGRA",
                90,
                f"Usada como banco em {vezes} pagamento(s) do histórico da empresa.",
                referencia_bancaria(banco, numero.group(0)),
            ),
        )


# ---------------------------------------------------------------- aprender


def _conta_atual(lancamentos: list[LancamentoHistorico]) -> tuple[int, float]:
    """(conta atual, quanto dela no uso recente). Uso recente estável (2+ seguidas) = mudança de prática."""
    ordenados = sorted(lancamentos, key=lambda lancamento: (lancamento.data, lancamento.id))
    ultima = ordenados[-1].contrapartida_id
    seguidas = 0
    for lancamento in reversed(ordenados):
        if lancamento.contrapartida_id != ultima:
            break
        seguidas += 1
    if seguidas >= 2 or len(ordenados) == 1:
        return ultima, 1.0
    recentes = ordenados[-5:]
    contagem = Counter(lancamento.contrapartida_id for lancamento in recentes)
    ultima_vez = {lancamento.contrapartida_id: lancamento.data for lancamento in recentes}
    melhor = max(contagem, key=lambda conta: (contagem[conta], ultima_vez[conta]))
    return melhor, contagem[melhor] / len(recentes)


def _valores_recorrentes(lancamentos: list[LancamentoHistorico]) -> list[str]:
    """Valores que aparecem 2+ vezes, o mais recente primeiro (o salário atual antes do antigo)."""
    contagem = Counter(lancamento.valor for lancamento in lancamentos)
    ultima = {}
    for lancamento in lancamentos:
        ultima[lancamento.valor] = max(lancamento.data, ultima.get(lancamento.valor, lancamento.data))
    repetidos = [valor for valor, vezes in contagem.items() if vezes >= 2]
    return [str(v) for v in sorted(repetidos, key=lambda v: (ultima[v], contagem[v]), reverse=True)[:5]]


def _mais_recente(lancamentos, atributo: str):
    for lancamento in sorted(lancamentos, key=lambda item: (item.data, item.id), reverse=True):
        if valor := getattr(lancamento, atributo):
            return valor
    return None


def _resumir(lancamentos: list[LancamentoHistorico], reduzido: dict[int, int]) -> dict[str, Any]:
    conta_id, parte = _conta_atual(lancamentos)
    por_natureza = {}
    grupos = defaultdict(list)
    for lancamento in lancamentos:
        if chave := normalizar_natureza(lancamento.natureza):
            grupos[chave].append(lancamento)
    for chave, itens in grupos.items():
        conta_natureza, parte_natureza = _conta_atual(itens)
        por_natureza[chave] = {
            "natureza": natureza_para_exibir(_mais_recente(itens, "natureza")),
            "conta": reduzido[conta_natureza],
            "ocorrencias": len(itens),
            "firme": parte_natureza >= 0.7,
            "valores": _valores_recorrentes(itens),
        }
    contas_naturezas = {item["conta"] for item in por_natureza.values()}
    explicado = len(por_natureza) > 1 and len(contas_naturezas) > 1 and all(i["firme"] for i in por_natureza.values())
    contas = Counter(lancamento.contrapartida_id for lancamento in lancamentos)
    ultima_por_conta = {}
    for lancamento in lancamentos:
        anterior = ultima_por_conta.get(lancamento.contrapartida_id)
        ultima_por_conta[lancamento.contrapartida_id] = max(lancamento.data, anterior or lancamento.data)
    return {
        "conta_id": conta_id,
        "ambiguo": parte < 0.7 and not explicado,
        "natureza": natureza_para_exibir(_mais_recente(lancamentos, "natureza")),
        "ocorrencias": len(lancamentos),
        "total": sum((lancamento.valor for lancamento in lancamentos), Decimal("0")),
        "ultima_data": max(lancamento.data for lancamento in lancamentos),
        "detalhes": {
            "contas": [
                {"conta": reduzido[c], "ocorrencias": n, "ultima": ultima_por_conta[c].isoformat()}
                for c, n in contas.most_common()
            ],
            "por_natureza": por_natureza if len(por_natureza) > 1 else {},
            "valores": _valores_recorrentes(lancamentos),
        },
    }


@dataclass
class ResultadoAprendizado:
    fornecedores: int = 0
    clientes: int = 0
    palavras: int = 0
    ambiguos: int = 0

    def resumo(self) -> str:
        texto = (
            f"🤖 Aprendido: {self.fornecedores} fornecedor(es)/favorecido(s), {self.clientes} cliente(s) "
            f"e {self.palavras} palavra(s)-chave."
        )
        if self.ambiguos:
            texto += f" {self.ambiguos} ficaram ambíguos: escolha a conta na aba Aprendizado."
        return texto


def aprender(sessao: Session, empresa: Empresa) -> ResultadoAprendizado:
    """Recalcula os padrões a partir de TODO o histórico da empresa. A escolha do usuário é mantida."""
    lancamentos = list(
        sessao.scalars(
            select(LancamentoHistorico).where(
                LancamentoHistorico.empresa_id == empresa.id,
                LancamentoHistorico.contrapartida_id.is_not(None),
                LancamentoHistorico.sentido.in_(("SAIDA", "ENTRADA")),
            )
        )
    )
    reduzido = dict(
        sessao.execute(
            select(ContaContabil.id, ContaContabil.reduzido).where(ContaContabil.empresa_id == empresa.id)
        ).all()
    )
    existentes = {(p.tipo, p.chave): p for p in sessao.scalars(select(Padrao).where(Padrao.empresa_id == empresa.id))}

    # favorecidos: agrupados pelo nome normalizado; nomes diferentes com o mesmo CNPJ viram um só
    por_nome = defaultdict(list)
    for lancamento in lancamentos:
        tipo = "FORNECEDOR" if lancamento.sentido == "SAIDA" else "CLIENTE"
        if chave := normalizar_nome(lancamento.favorecido):
            por_nome[(tipo, chave)].append(lancamento)
    grupos, dono_do_cnpj = defaultdict(list), {}
    for (tipo, chave), itens in sorted(por_nome.items(), key=lambda item: (-len(item[1]), item[0])):
        cnpjs = {lancamento.cnpj_cpf for lancamento in itens if lancamento.cnpj_cpf}
        alvo = next((dono_do_cnpj[(tipo, c)] for c in cnpjs if (tipo, c) in dono_do_cnpj), (tipo, chave))
        grupos[alvo].extend(itens)
        for cnpj in cnpjs:
            dono_do_cnpj.setdefault((tipo, cnpj), alvo)

    # palavras-chave: natureza usada por 2+ favorecidos sempre na mesma conta
    por_natureza = defaultdict(list)
    for lancamento in lancamentos:
        if len(chave := normalizar_natureza(lancamento.natureza)) >= 4:
            por_natureza[chave].append(lancamento)

    resultado = ResultadoAprendizado()
    produzidos = set(grupos)
    sessao.info["auditoria_em_bloco"] = True  # um evento no log, não uma linha por padrão
    try:
        for (tipo, chave), itens in grupos.items():
            dados = _resumir(itens, reduzido)
            dados["nome"] = _mais_recente(itens, "favorecido")
            dados["cnpj_cpf"] = _mais_recente(itens, "cnpj_cpf")
            padrao = _gravar_padrao(sessao, empresa, existentes, tipo, chave, dados)
            resultado.fornecedores += tipo == "FORNECEDOR"
            resultado.clientes += tipo == "CLIENTE"
            resultado.ambiguos += padrao.ambiguo and padrao.ativo
        for chave, itens in por_natureza.items():
            favorecidos = {normalizar_nome(lancamento.favorecido) for lancamento in itens}
            conta_id, parte = _conta_atual(itens)
            if len(favorecidos) < 2 or parte < 0.7:
                continue
            dados = _resumir(itens, reduzido)
            nome = natureza_para_exibir(_mais_recente(itens, "natureza"))
            dados.update(nome=nome, cnpj_cpf=None, conta_id=conta_id, ambiguo=False)
            _gravar_padrao(sessao, empresa, existentes, "PALAVRA", chave, dados)
            produzidos.add(("PALAVRA", chave))
            resultado.palavras += 1
        # padrão aprendido que o histórico não sustenta mais (ex.: dois nomes do mesmo CNPJ que viraram um só)
        # sai; o que o usuário escolheu à mão fica
        for chave, padrao in existentes.items():
            if chave not in produzidos and padrao.origem == "APRENDIDO":
                sessao.delete(padrao)
        sessao.flush()
    finally:
        sessao.info.pop("auditoria_em_bloco", None)
    registrar_evento(sessao, "APRENDER", detalhe=f"{empresa.nome}: {resultado.resumo()}")
    return resultado


def _gravar_padrao(sessao, empresa, existentes, tipo: str, chave: str, dados: dict[str, Any]) -> Padrao:
    padrao = existentes.get((tipo, chave))
    if padrao is None:
        padrao = Padrao(empresa_id=empresa.id, tipo=tipo, chave=chave, ativo=True, origem="APRENDIDO")
        sessao.add(padrao)
        existentes[(tipo, chave)] = padrao
    padrao.nome = (dados["nome"] or chave)[:200]
    padrao.cnpj_cpf = dados["cnpj_cpf"]
    padrao.natureza = (dados["natureza"] or "")[:200] or None
    padrao.ocorrencias = dados["ocorrencias"]
    padrao.total = dados["total"]
    padrao.ultima_data = dados["ultima_data"]
    padrao.detalhes = dados["detalhes"]
    if padrao.origem != "USUARIO":  # a escolha do usuário vale mais que o aprendido
        padrao.conta_id = dados["conta_id"]
        padrao.ambiguo = dados["ambiguo"]
    return padrao


# ---------------------------------------------------------------- consultas e ações das telas


def resumo_historico(sessao: Session, empresa: Empresa) -> dict[str, Any]:
    total, inicio, fim = sessao.execute(
        select(func.count(), func.min(LancamentoHistorico.data), func.max(LancamentoHistorico.data)).where(
            LancamentoHistorico.empresa_id == empresa.id
        )
    ).one()
    contagem = dict(
        sessao.execute(
            select(Padrao.tipo, func.count()).where(Padrao.empresa_id == empresa.id, Padrao.ativo).group_by(Padrao.tipo)
        ).all()
    )
    ambiguos = sessao.scalar(
        select(func.count()).select_from(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.ambiguo, Padrao.ativo)
    )
    return {"lancamentos": total, "de": inicio, "ate": fim, "padroes": contagem, "ambiguos": ambiguos}


def listar_padroes(
    sessao: Session, empresa: Empresa, tipo: str, texto: str = "", so_ambiguos: bool = False
) -> list[Padrao]:
    consulta = select(Padrao).where(Padrao.empresa_id == empresa.id, Padrao.tipo == tipo)
    if so_ambiguos:
        consulta = consulta.where(Padrao.ambiguo, Padrao.ativo)
    if texto := texto.strip():
        documento = normalizar_documento(texto)
        condicao = func.unaccent(Padrao.nome).ilike(func.unaccent(f"%{texto}%"))
        if documento:
            condicao = condicao | Padrao.cnpj_cpf.like(f"%{documento}%")
        consulta = consulta.where(condicao)
    ordem = (Padrao.ativo.desc(), Padrao.ambiguo.desc(), Padrao.ocorrencias.desc(), Padrao.nome)
    return list(sessao.scalars(consulta.order_by(*ordem)))


def despesas_por_conta(sessao: Session, empresa: Empresa) -> list[tuple[ContaContabil, int, Decimal]]:
    """Resumo para conferência (§3.3): quanto foi pago em cada conta, pelo histórico."""
    return list(
        sessao.execute(
            select(ContaContabil, func.count(), func.sum(LancamentoHistorico.valor))
            .join(LancamentoHistorico, LancamentoHistorico.contrapartida_id == ContaContabil.id)
            .where(LancamentoHistorico.empresa_id == empresa.id, LancamentoHistorico.sentido == "SAIDA")
            .group_by(ContaContabil.id)
            .order_by(func.sum(LancamentoHistorico.valor).desc())
        ).all()
    )


def documento_formatado(padrao: Padrao) -> str:
    return formatar_documento(padrao.cnpj_cpf) if padrao.cnpj_cpf else ""


# ---------------------------------------------------------------- perfil da empresa (IA)

INSTRUCOES_PERFIL = """Você é contador(a) do escritório Zera Contabilidade. Escreva o PERFIL de uma \
empresa-cliente para orientar a classificação automática dos extratos bancários dela: atividade, \
principais fornecedores e despesas típicas, e como os pagamentos costumam ser lançados (direto em \
despesa ou baixando contas do passivo, como salários a pagar). No máximo 120 palavras, em português, \
frases curtas, sem inventar nada que não esteja nos dados."""


def gerar_perfil(sessao: Session, empresa: Empresa, usuario: Usuario | None = None) -> str:
    fornecedores = listar_padroes(sessao, empresa, "FORNECEDOR")[:20]
    contas = despesas_por_conta(sessao, empresa)[:12]
    publicos = empresa.dados_publicos or {}
    linhas = [
        f"Empresa: {empresa.nome}; regime: {empresa.regime.rotulo if empresa.regime else 'não informado'}; "
        f"natureza jurídica: {publicos.get('natureza_juridica', '-')}; atividade: {publicos.get('atividade', '-')}.",
        "Principais favorecidos (nome | conta | natureza | vezes):",
        *(
            f"- {p.nome} | {p.conta.rotulo if p.conta else '-'} | {p.natureza or '-'} | {p.ocorrencias}"
            for p in fornecedores
        ),
        "Pagamentos por conta (conta | lançamentos | total R$):",
        *(f"- {conta.rotulo} | {vezes} | {total}" for conta, vezes, total in contas),
    ]
    pedido = PedidoIA(
        finalidade="perfil_empresa",
        instrucoes=INSTRUCOES_PERFIL,
        pergunta="\n".join(linhas),
        esquema={
            "type": "object",
            "properties": {"perfil": {"type": "string"}},
            "required": ["perfil"],
            "additionalProperties": False,
        },
        max_tokens=1500,
    )
    resposta = chamar_ia(sessao, pedido, empresa, usuario)
    perfil = str(resposta.dados.get("perfil") or "").strip()
    if not perfil:
        raise ErroIA("A IA não escreveu o perfil. Tente de novo.")
    empresa.perfil_ia = perfil[:2000]
    empresa.perfil_ia_em = datetime.now(UTC)
    return empresa.perfil_ia
