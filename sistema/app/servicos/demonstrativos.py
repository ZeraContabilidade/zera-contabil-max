"""Demonstrativo da prestação de contas junto com o extrato (pedido de 15/10/2026).

O extrato diz QUANDO e QUANTO saiu do banco; o demonstrativo diz PARA QUEM e O QUÊ — o favorecido de verdade (o
banco escreve “LYTEX”, o demonstrativo “SIEMACO - PLANO ODONTOLÓGICO”), o CNPJ e o nº da nota. Cada linha do
demonstrativo é ligada ao movimento do extrato:
1. pelo nº da transferência (o “TRANSF. Nº” é o documento do banco: 80301 = “80.301”) e o valor;
2. pela data do pagamento e o valor;
3. pelo valor, a até 3 dias, quando só um movimento serve;
4. rateio: várias linhas com o mesmo nº e dia que somam uma transferência só (FGTS + FGTS consignado = 7.083,27):
   a linha do banco é DESDOBRADA — uma parte (movimento) para cada linha, cada uma com o seu lançamento.
A classificação usa o que o demonstrativo diz (`classificacao._pelo_demonstrativo`) e o histórico sai como o
escritório fazia na planilha antiga: “FAVORECIDO - ESPECIFICAÇÃO - Nº DO DOCUMENTO”.
Um demonstrativo por empresa (creche) e mês: mandar de novo troca o anterior.
"""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.auditoria import registrar_evento
from app.leitores.demonstrativo import LinhaLida, ler_demonstrativo
from app.modelos import ContaBancaria, Empresa, Importacao, LinhaDemonstrativo, MovimentoExtrato, Usuario
from app.servicos.armazenamento import guardar_arquivo
from app.servicos.classificacao import semelhanca
from app.servicos.competencia import Periodo, nome_competencia
from app.servicos.documentos import formatar_documento
from app.servicos.extratos import mesma_conta, reais_br
from app.servicos.plano import Aviso, ErroLeitura

FOLGA_DIAS = 3
MAXIMO_RATEIO = 16  # linhas de um mesmo nº/dia que o sistema tenta combinar


def _digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "").lstrip("0")


@dataclass
class ResultadoCruzamento:
    casadas: int = 0
    desdobradas: int = 0  # linhas do banco desdobradas (rateio)
    partes: int = 0  # lançamentos que saíram dos desdobramentos
    protegidas: list[str] = field(default_factory=list)  # rateio achado, mas a linha já foi conferida/exportada

    def somar(self, outro: "ResultadoCruzamento") -> None:
        self.casadas += outro.casadas
        self.desdobradas += outro.desdobradas
        self.partes += outro.partes
        self.protegidas += outro.protegidas


# ---------------------------------------------------------------- cruzar com o extrato


def _contas_do_mes(sessao: Session, empresa: Empresa, linhas: list[LinhaDemonstrativo]) -> set[int]:
    return {linha.conta_bancaria_id for linha in linhas if linha.conta_bancaria_id}


def _candidatos(sessao: Session, empresa: Empresa, mes: date, contas: set[int]) -> list[MovimentoExtrato]:
    inicio, fim = Periodo.do_mes(mes).limites
    consulta = select(MovimentoExtrato).where(
        MovimentoExtrato.empresa_id == empresa.id,
        MovimentoExtrato.data.between(inicio - timedelta(days=FOLGA_DIAS), fim + timedelta(days=FOLGA_DIAS)),
        MovimentoExtrato.desdobrado.is_(False),
        MovimentoExtrato.parte_de_id.is_(None),
    )
    if contas:
        consulta = consulta.where(MovimentoExtrato.conta_bancaria_id.in_(contas))
    # pergunta ao banco (e não ao objeto na memória, que pode lembrar de uma linha que acabou de ser apagada)
    ligado = exists().where(LinhaDemonstrativo.movimento_id == MovimentoExtrato.id)
    return list(sessao.scalars(consulta.where(~ligado).order_by(MovimentoExtrato.data, MovimentoExtrato.ordem)))


def _perto(linha: LinhaDemonstrativo, movimento: MovimentoExtrato, dias: int = FOLGA_DIAS) -> bool:
    return linha.data is None or abs((movimento.data - linha.data).days) <= dias


def _distancia(linha: LinhaDemonstrativo, movimento: MovimentoExtrato) -> tuple[int, int]:
    """Para escolher entre movimentos do mesmo valor: o nome parecido primeiro, depois a data mais perto."""
    nome = semelhanca(movimento.complemento or "", linha.nome) if linha.nome else 0
    return -nome, abs((movimento.data - (linha.data or movimento.data)).days)


def _subconjunto(linhas: list[LinhaDemonstrativo], alvo: Decimal) -> list[LinhaDemonstrativo] | None:
    """Linhas que somam o valor da transferência: primeiro as seguidas (na ordem do demonstrativo), depois qualquer
    combinação."""
    for i in range(len(linhas)):
        soma = Decimal("0")
        for j in range(i, len(linhas)):
            soma += linhas[j].valor
            if soma == alvo and j > i:
                return linhas[i : j + 1]
            if soma > alvo:
                break
    if len(linhas) > MAXIMO_RATEIO:
        return None
    for tamanho in range(2, len(linhas) + 1):
        for combinacao in combinations(linhas, tamanho):
            if sum((linha.valor for linha in combinacao), Decimal("0")) == alvo:
                return list(combinacao)
    return None


def _protegida(movimento: MovimentoExtrato) -> bool:
    sugestao = movimento.sugestao
    return bool(
        sugestao and (sugestao.status == "EXPORTADO" or sugestao.conferido_por_id or sugestao.origem == "USUARIO")
    )


def _desdobrar(sessao: Session, movimento: MovimentoExtrato, linhas: list[LinhaDemonstrativo]) -> None:
    """A linha do banco vira uma parte para cada linha do rateio (a soma é a mesma; o saldo do extrato não muda)."""
    if movimento.sugestao is not None:
        sessao.delete(movimento.sugestao)
        sessao.flush()
        sessao.expire(movimento, ["sugestao"])
    movimento.desdobrado = True
    for numero, linha in enumerate(linhas, start=1):
        parte = MovimentoExtrato(
            empresa_id=movimento.empresa_id,
            conta_bancaria_id=movimento.conta_bancaria_id,
            extrato_id=movimento.extrato_id,
            ordem=movimento.ordem,
            data=movimento.data,
            valor=linha.valor,
            sentido=movimento.sentido,
            historico=movimento.historico,
            complemento=(linha.nome or movimento.complemento or "")[:200] or None,
            documento=movimento.documento,
            codigo_banco=movimento.codigo_banco,
            hash=hashlib.sha256(f"{movimento.hash}|parte|{numero}".encode()).hexdigest(),
            parte_de_id=movimento.id,
        )
        sessao.add(parte)
        sessao.flush()
        linha.movimento_id = parte.id
        linha.conta_bancaria_id = movimento.conta_bancaria_id


def cruzar_mes(sessao: Session, empresa: Empresa, mes: date) -> ResultadoCruzamento:
    """Liga as linhas do demonstrativo do mês que ainda não têm movimento. Pode rodar quantas vezes quiser (cada
    extrato novo que chega tenta de novo)."""
    resultado = ResultadoCruzamento()
    todas = list(
        sessao.scalars(
            select(LinhaDemonstrativo)
            .where(LinhaDemonstrativo.empresa_id == empresa.id, LinhaDemonstrativo.mes == mes)
            .order_by(LinhaDemonstrativo.ordem)
        )
    )
    soltas = [linha for linha in todas if linha.movimento_id is None]
    if not soltas:
        return resultado
    movimentos = _candidatos(sessao, empresa, mes, _contas_do_mes(sessao, empresa, todas))

    def ligar(linha: LinhaDemonstrativo, movimento: MovimentoExtrato) -> None:
        linha.movimento_id = movimento.id
        linha.movimento = movimento
        linha.conta_bancaria_id = movimento.conta_bancaria_id
        soltas.remove(linha)
        movimentos.remove(movimento)
        resultado.casadas += 1

    # 1. nº da transferência + valor; 2. data + valor
    for chave in (
        lambda linha, m: linha.transferencia and _digitos(m.documento) == _digitos(linha.transferencia),
        lambda linha, m: linha.data == m.data,
    ):
        for linha in list(soltas):
            achados = [
                m
                for m in movimentos
                if m.sentido == linha.sentido and m.valor == linha.valor and _perto(linha, m) and chave(linha, m)
            ]
            if achados:  # salários iguais no mesmo dia: desempata pelo nome que o banco escreveu
                ligar(linha, min(achados, key=lambda m: _distancia(linha, m)))
    # 3. só o valor, a até 3 dias: quando só um movimento serve (ou só um tem o nome parecido)
    for linha in list(soltas):
        achados = [m for m in movimentos if m.sentido == linha.sentido and m.valor == linha.valor and _perto(linha, m)]
        parecidos = [m for m in achados if linha.nome and semelhanca(m.complemento or "", linha.nome) >= 75]
        if len(achados) == 1 or len(parecidos) == 1:
            ligar(linha, achados[0] if len(achados) == 1 else parecidos[0])
    # 4. rateio: várias linhas do mesmo nº (ou dia) para uma transferência só
    for movimento in list(movimentos):
        grupo = [
            linha
            for linha in soltas
            if linha.sentido == movimento.sentido
            and _perto(linha, movimento)
            and (
                (linha.transferencia and _digitos(linha.transferencia) == _digitos(movimento.documento))
                or linha.data == movimento.data
            )
        ]
        if len(grupo) < 2 or (partes := _subconjunto(grupo, movimento.valor)) is None:
            continue
        if _protegida(movimento):
            resultado.protegidas.append(
                f"{movimento.data:%d/%m} R$ {reais_br(movimento.valor)} {movimento.complemento or movimento.historico}"
            )
            continue
        _desdobrar(sessao, movimento, partes)
        for linha in partes:
            soltas.remove(linha)
        movimentos.remove(movimento)
        resultado.desdobradas += 1
        resultado.partes += len(partes)
    sessao.flush()
    return resultado


def cruzar_periodo(sessao: Session, empresa: Empresa, inicio: date, fim: date) -> ResultadoCruzamento:
    resultado = ResultadoCruzamento()
    meses = sessao.scalars(
        select(LinhaDemonstrativo.mes)
        .where(LinhaDemonstrativo.empresa_id == empresa.id, LinhaDemonstrativo.mes.between(inicio.replace(day=1), fim))
        .distinct()
    ).all()
    for mes in meses:
        resultado.somar(cruzar_mes(sessao, empresa, mes))
    return resultado


# ---------------------------------------------------------------- importar


def desfazer_mes(sessao: Session, empresa: Empresa, mes: date) -> None:
    """Tira o demonstrativo do mês (antes de trocar por outro): as partes do rateio somem e a linha do banco volta."""
    linhas = list(
        sessao.scalars(
            select(LinhaDemonstrativo).where(LinhaDemonstrativo.empresa_id == empresa.id, LinhaDemonstrativo.mes == mes)
        )
    )
    partes = [linha.movimento for linha in linhas if linha.movimento is not None and linha.movimento.parte_de_id]
    if travadas := [p for p in partes if _protegida(p)]:
        raise ErroLeitura(
            f"O demonstrativo de {nome_competencia(mes)} já tem {len(travadas)} lançamento(s) de rateio conferido(s) "
            "ou exportado(s). Reabra a exportação (ou as linhas na Revisão) antes de mandar o demonstrativo de novo."
        )
    originais = {p.parte_de_id for p in partes}
    ligados = [linha.movimento for linha in linhas if linha.movimento is not None and not linha.movimento.parte_de_id]
    for parte in partes:
        if parte.sugestao is not None:
            sessao.delete(parte.sugestao)
    sessao.flush()
    for linha in linhas:
        sessao.delete(linha)
    sessao.flush()
    for parte in partes:
        sessao.delete(parte)
    sessao.flush()
    for original in originais:
        if movimento := sessao.get(MovimentoExtrato, original):
            movimento.desdobrado = False
    for movimento in ligados:  # a linha do demonstrativo que estava ligada a ele não existe mais
        sessao.expire(movimento, ["linha_demonstrativo"])
    sessao.flush()


def _contas_do_demonstrativo(
    sessao: Session, empresa: Empresa, agencia: str, numeros: list[str]
) -> list[ContaBancaria]:
    contas = sessao.scalars(select(ContaBancaria).where(ContaBancaria.empresa_id == empresa.id)).all()
    return [c for c in contas if any(mesma_conta(c, agencia, numero) for numero in numeros)]


def _conferir_empresa(sessao: Session, empresa: Empresa, nome: str, lido) -> list[ContaBancaria]:
    """O demonstrativo é desta creche? Pela conta do banco (as creches da mesma associação dividem o CNPJ)."""
    if lido.cnpj and empresa.cnpj_cpf and lido.cnpj != empresa.cnpj_cpf:
        raise ErroLeitura(
            f"Este demonstrativo é da {lido.creche or 'outra entidade'} (CNPJ {formatar_documento(lido.cnpj)}), e "
            f"esta empresa tem o CNPJ {empresa.documento_formatado}. Confira se escolheu a creche certa."
        )
    if not lido.contas:
        return []
    for numero in lido.contas:  # a conta é de outro cadastro?
        outras = sessao.scalars(select(ContaBancaria).where(ContaBancaria.empresa_id != empresa.id)).all()
        dona = next((c for c in outras if mesma_conta(c, lido.agencia, numero)), None)
        if dona is not None:
            outra = sessao.get(Empresa, dona.empresa_id)
            raise ErroLeitura(
                f"Este demonstrativo é da {lido.creche or 'creche'} (conta {numero}), que está no cadastro "
                f"{outra.nome}. Confira se escolheu a creche certa."
            )
    return _contas_do_demonstrativo(sessao, empresa, lido.agencia, lido.contas)


def importar_demonstrativo(
    sessao: Session, empresa: Empresa, nome_arquivo: str, conteudo: bytes, usuario: Usuario | None
) -> Importacao:
    from app.servicos.classificacao import classificar

    lido = ler_demonstrativo(nome_arquivo, conteudo)
    contas = _conferir_empresa(sessao, empresa, nome_arquivo, lido)
    desfazer_mes(sessao, empresa, lido.mes)
    arquivo = guardar_arquivo(sessao, empresa, "DEMONSTRATIVO", nome_arquivo, conteudo, usuario)
    importacao = Importacao(
        empresa_id=empresa.id, tipo="DEMONSTRATIVO", arquivo_id=arquivo.id, usuario_id=usuario.id if usuario else None
    )
    sessao.add(importacao)
    sessao.flush()
    conta_unica = contas[0].id if len(contas) == 1 else None
    sessao.add_all(_linha_do_banco(empresa, importacao, lido.mes, linha, conta_unica) for linha in lido.linhas)
    sessao.flush()
    cruzamento = cruzar_mes(sessao, empresa, lido.mes)
    inicio, fim = Periodo.do_mes(lido.mes).limites
    classificacao = classificar(sessao, empresa, inicio, fim)
    situacao = situacao_do_mes(sessao, empresa, lido.mes)
    avisos = list(lido.avisos)
    if not contas:
        avisos.append(
            Aviso(
                f"O extrato da conta {', '.join(lido.contas) or 'do demonstrativo'} ainda não está no sistema: as "
                "linhas do demonstrativo ficam guardadas e são ligadas quando o extrato chegar."
            )
        )
    if situacao.sem_extrato and contas:
        avisos.append(
            Aviso(
                f"{len(situacao.sem_extrato)} linha(s) do demonstrativo não estão no extrato.",
                [linha_texto(linha) for linha in situacao.sem_extrato],
            )
        )
    if cruzamento.protegidas:
        avisos.append(
            Aviso(
                "Rateio achado, mas a linha do banco já foi conferida ou exportada: ficou como estava.",
                cruzamento.protegidas,
            )
        )
    importacao.resumo = {
        "creche": lido.creche,
        "mes": lido.mes.isoformat(),
        "contas": lido.contas,
        "pagamentos": len(lido.pagamentos),
        "receitas": len(lido.receitas),
        "total_despesas": str(sum((linha.valor for linha in lido.pagamentos), Decimal("0"))),
        "ligadas": situacao.ligadas,
        "desdobradas": cruzamento.desdobradas,
        "partes": cruzamento.partes,
        "sem_extrato": len(situacao.sem_extrato),
        "classificacao": classificacao.resumo(),
    }
    importacao.avisos = [asdict(aviso) for aviso in avisos]
    registrar_evento(
        sessao,
        "IMPORTAR_DEMONSTRATIVO",
        detalhe=f"{empresa.nome}: demonstrativo de {nome_competencia(lido.mes)} — {len(lido.pagamentos)} pagamento(s), "
        f"{situacao.ligadas} ligado(s) ao extrato, {cruzamento.desdobradas} rateio(s)",
    )
    return importacao


def _linha_do_banco(
    empresa: Empresa, importacao: Importacao, mes: date, linha: LinhaLida, conta_id: int | None
) -> LinhaDemonstrativo:
    return LinhaDemonstrativo(
        empresa_id=empresa.id,
        importacao_id=importacao.id,
        mes=mes,
        ordem=linha.ordem,
        sentido=linha.sentido,
        valor=linha.valor,
        favorecido=linha.favorecido,
        nome=linha.nome,
        cnpj_cpf=linha.cnpj_cpf,
        especificacao=linha.especificacao,
        grupo=linha.grupo,
        item=linha.item,
        documento_tipo=linha.documento_tipo,
        documento_numero=linha.documento_numero,
        documento_data=linha.documento_data,
        transferencia=linha.transferencia,
        data=linha.data,
        conta_bancaria_id=conta_id,
    )


# ---------------------------------------------------------------- para a tela


def linha_texto(linha: LinhaDemonstrativo) -> str:
    quem = linha.favorecido or linha.especificacao
    data = f"{linha.data:%d/%m} " if linha.data else ""
    return f"{data}R$ {reais_br(linha.valor)} — {quem}" + (f" ({linha.especificacao})" if linha.favorecido else "")


@dataclass
class SituacaoDemonstrativo:
    mes: date
    importacao: Importacao | None
    linhas: int = 0
    ligadas: int = 0
    rateios: int = 0  # linhas do banco desdobradas
    sem_extrato: list[LinhaDemonstrativo] = field(default_factory=list)  # no demonstrativo, não no extrato
    sem_demonstrativo: list[MovimentoExtrato] = field(default_factory=list)  # pagamento do extrato sem linha


def situacao_do_mes(sessao: Session, empresa: Empresa, mes: date) -> SituacaoDemonstrativo:
    from app.servicos.classificacao import aplicacao_automatica

    linhas = list(
        sessao.scalars(
            select(LinhaDemonstrativo)
            .where(LinhaDemonstrativo.empresa_id == empresa.id, LinhaDemonstrativo.mes == mes)
            .order_by(LinhaDemonstrativo.ordem)
        )
    )
    situacao = SituacaoDemonstrativo(mes, linhas[0].importacao if linhas else None, len(linhas))
    if not linhas:
        return situacao
    situacao.ligadas = sum(1 for linha in linhas if linha.movimento_id)
    situacao.rateios = len(
        {linha.movimento.parte_de_id for linha in linhas if linha.movimento and linha.movimento.parte_de_id}
    )
    situacao.sem_extrato = [linha for linha in linhas if linha.movimento_id is None and linha.sentido == "SAIDA"]
    contas = _contas_do_mes(sessao, empresa, linhas)
    if contas:
        inicio, fim = Periodo.do_mes(mes).limites
        pagamentos = sessao.scalars(
            select(MovimentoExtrato)
            .where(
                MovimentoExtrato.empresa_id == empresa.id,
                MovimentoExtrato.conta_bancaria_id.in_(contas),
                MovimentoExtrato.data.between(inicio, fim),
                MovimentoExtrato.sentido == "SAIDA",
                MovimentoExtrato.desdobrado.is_(False),
            )
            .order_by(MovimentoExtrato.data, MovimentoExtrato.ordem)
        )
        situacao.sem_demonstrativo = [
            m
            for m in pagamentos
            if m.linha_demonstrativo is None
            and not aplicacao_automatica(m)
            and not (
                m.sugestao and (m.sugestao.status == "IGNORADO" or m.sugestao.origem in ("TRANSFERENCIA", "REGRA"))
            )
        ]
    return situacao


def meses_com_demonstrativo(sessao: Session, empresa: Empresa, periodo: Periodo) -> list[SituacaoDemonstrativo]:
    inicio, fim = periodo.limites
    meses = sessao.scalars(
        select(LinhaDemonstrativo.mes)
        .where(LinhaDemonstrativo.empresa_id == empresa.id, LinhaDemonstrativo.mes.between(inicio, fim))
        .distinct()
        .order_by(LinhaDemonstrativo.mes)
    ).all()
    return [situacao_do_mes(sessao, empresa, mes) for mes in meses]
