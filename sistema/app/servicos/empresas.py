"""Regras do cadastro de empresas."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.modelos import Empresa, Regime, Usuario
from app.modelos.empresa import LIMIAR_MINIMO, LIMIAR_PADRAO
from app.servicos import cnpj_publico
from app.servicos.cnpj_publico import DadosPublicos
from app.servicos.complemento import MODELO_PADRAO, problema_no_modelo
from app.servicos.documentos import formatar_documento, normalizar_documento, tipo_documento

TAMANHOS = {"razao_social": 200, "nome_curto": 80}
ROTULOS = {"razao_social": "razão social", "nome_curto": "nome curto", "regime": "regime", "cnpj_cpf": "CNPJ"}


def ler_formulario(sessao: Session, form: dict[str, str | None], empresa: Empresa | None = None):
    """Confere o formulário. Devolve (valores prontos para gravar, erros em português)."""
    erros: list[str] = []
    valores: dict = {}
    ignorar_id = empresa.id if empresa else 0

    codigo = (form.get("codigo_dominio") or "").strip()
    if not codigo.isdigit() or not 0 < int(codigo) < 10_000_000:
        erros.append("Informe o código da empresa no Domínio (só números, ex.: 230).")
    else:
        valores["codigo_dominio"] = int(codigo)

    filial = empresa.codigo_filial if empresa else None
    if "codigo_filial" in form:
        texto = (form.get("codigo_filial") or "").strip()
        if texto and (not texto.isdigit() or not 0 < int(texto) < 10_000_000):
            erros.append(
                "O código da filial é o código dela no Domínio (só números, ex.: 231). Sem filial, deixe vazio."
            )
        else:
            filial = int(texto) if texto else None
            valores["codigo_filial"] = filial

    if "codigo_dominio" in valores:  # cada filial é um cadastro: o par código + filial não pode repetir
        outra = sessao.scalar(
            select(Empresa).where(
                Empresa.codigo_dominio == valores["codigo_dominio"],
                Empresa.codigo_filial.is_(None) if filial is None else Empresa.codigo_filial == filial,
                Empresa.id != ignorar_id,
            )
        )
        if outra and filial:
            erros.append(
                f"A filial {filial} do código {valores['codigo_dominio']} já é da empresa {outra.nome}. "
                "Confira os códigos no Domínio."
            )
        elif outra:
            erros.append(
                f"O código {valores['codigo_dominio']} já é da empresa {outra.nome}. Confira o código no Domínio — "
                "se esta for uma filial, preencha também o código da filial."
            )

    for campo, tamanho in TAMANHOS.items():
        texto = " ".join((form.get(campo) or "").split())
        if len(texto) > tamanho:
            erros.append(f"A {ROTULOS[campo]} pode ter no máximo {tamanho} letras.")
        valores[campo] = texto or None

    documento = normalizar_documento(form.get("cnpj_cpf"))
    if documento and tipo_documento(documento) is None:
        erros.append(f"O CNPJ/CPF {formatar_documento(documento)} não é válido — confira os números.")
    elif documento:
        outra = sessao.scalar(select(Empresa).where(Empresa.cnpj_cpf == documento, Empresa.id != ignorar_id))
        if outra:
            erros.append(
                f"O CNPJ/CPF {formatar_documento(documento)} já está na empresa {outra.nome} "
                f"(código {outra.rotulo_codigo})."
            )
    valores["cnpj_cpf"] = documento or None

    regime = form.get("regime") or ""
    try:
        valores["regime"] = Regime(regime) if regime else None
    except ValueError:
        erros.append("Escolha o regime na lista.")

    responsavel = form.get("responsavel_id") or ""
    usuario = sessao.get(Usuario, int(responsavel)) if responsavel.isdigit() else None
    if responsavel and (usuario is None or not usuario.ativo):
        erros.append("Escolha o responsável na lista.")
    valores["responsavel_id"] = usuario.id if usuario else None

    valores["observacoes"] = (form.get("observacoes") or "").strip() or None

    if "modelo_complemento" in form:
        modelo = " ".join((form.get("modelo_complemento") or "").split())
        if problema := problema_no_modelo(modelo):
            erros.append(problema)
        valores["modelo_complemento"] = modelo or MODELO_PADRAO
    if "ativa" in form:
        valores["ativa"] = form["ativa"] is not None
    if "ia_ligada" in form:
        valores["ia_ligada"] = form["ia_ligada"] is not None
    if "exportacao_automatica" in form:
        valores["exportacao_automatica"] = form["exportacao_automatica"] is not None
    if "usa_conta_individual" in form:
        valores["usa_conta_individual"] = form["usa_conta_individual"] is not None
    if "grupo_fornecedores" in form:
        grupo = " ".join((form.get("grupo_fornecedores") or "").split())
        if len(grupo) > 40:
            erros.append("O grupo de fornecedores pode ter no máximo 40 letras (ex.: 2.1.3.01).")
        valores["grupo_fornecedores"] = grupo or None
    if "limiar_aprovacao" in form:
        texto = (form.get("limiar_aprovacao") or "").replace("%", "").strip()
        if not texto:
            valores["limiar_aprovacao"] = LIMIAR_PADRAO
        elif texto.isdigit() and LIMIAR_MINIMO <= int(texto) <= 100:
            valores["limiar_aprovacao"] = int(texto)
        else:
            erros.append(
                f"A aprovação automática vai de {LIMIAR_MINIMO}% a 100% (padrão {LIMIAR_PADRAO}%). "
                "Digite só o número, ex.: 90."
            )
    if "ia_limite_mensal_usd" in form:
        limite = _ler_dolares(form["ia_limite_mensal_usd"])
        if limite is False:
            erros.append("Informe o limite de IA em dólares (ex.: 5,00) ou deixe em branco.")
        else:
            valores["ia_limite_mensal_usd"] = limite
    return valores, erros


def _ler_dolares(texto: str | None) -> Decimal | None | bool:
    """'5,00' → Decimal('5.00'); vazio → None; inválido ou negativo → False."""
    texto = (texto or "").strip().replace("US$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return False
    return valor.quantize(Decimal("0.01")) if valor >= 0 else False


def aplicar_edicao(empresa: Empresa, valores: dict) -> None:
    """Grava o que o usuário mudou; campo alterado à mão perde o selo 🤖."""
    automaticos = list(empresa.campos_automaticos or [])
    for campo, valor in valores.items():
        if getattr(empresa, campo) != valor:
            setattr(empresa, campo, valor)
            if campo in automaticos:
                automaticos.remove(campo)
    empresa.campos_automaticos = automaticos


def aplicar_dados_publicos(empresa: Empresa, dados: DadosPublicos) -> list[str]:
    """Preenche o que está vazio ou ainda é automático; nunca apaga o que o usuário digitou."""
    automaticos = list(empresa.campos_automaticos or [])
    preenchidos = []
    sugestoes = {
        "razao_social": dados.razao_social[: TAMANHOS["razao_social"]],
        "nome_curto": (dados.nome_fantasia or "")[: TAMANHOS["nome_curto"]] or None,
        "regime": dados.regime,
    }
    for campo, valor in sugestoes.items():
        atual = getattr(empresa, campo)
        pode_mudar = atual in (None, "") or campo in automaticos
        if valor and pode_mudar and atual != valor:
            setattr(empresa, campo, valor)
            preenchidos.append(campo)
            if campo not in automaticos:
                automaticos.append(campo)
    empresa.campos_automaticos = automaticos
    empresa.dados_publicos = dados.resumo
    return preenchidos


@dataclass
class ResultadoConsulta:
    situacao: str  # "sem_cnpj", "falhou" ou "ok"
    preenchidos: list[str] = field(default_factory=list)


def completar_pelo_cnpj(empresa: Empresa) -> ResultadoConsulta:
    """Consulta pública do CNPJ e preenche o que estiver vazio (CPF não tem consulta pública)."""
    if not empresa.cnpj_cpf or tipo_documento(empresa.cnpj_cpf) != "CNPJ":
        return ResultadoConsulta("sem_cnpj")
    dados = cnpj_publico.consultar_cnpj(empresa.cnpj_cpf)
    if dados is None:
        return ResultadoConsulta("falhou")
    return ResultadoConsulta("ok", aplicar_dados_publicos(empresa, dados))


def descrever_campos(campos: list[str]) -> str:
    nomes = [ROTULOS[c] for c in campos]
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def buscar_empresas(sessao: Session, texto: str = "", responsavel_id: int | None = None) -> list[Empresa]:
    """Busca por nome (sem ligar para acentos), CNPJ ou código no Domínio (da empresa ou da filial)."""
    consulta = select(Empresa).options(joinedload(Empresa.responsavel))
    texto = texto.strip()
    if texto:
        padrao = func.unaccent(f"%{texto}%")
        condicoes = [
            func.unaccent(Empresa.razao_social).ilike(padrao),
            func.unaccent(Empresa.nome_curto).ilike(padrao),
            cast(Empresa.codigo_dominio, String) == texto,
            cast(Empresa.codigo_filial, String) == texto,
        ]
        if documento := normalizar_documento(texto):
            condicoes.append(Empresa.cnpj_cpf.like(f"%{documento}%"))
        consulta = consulta.where(or_(*condicoes))
    if responsavel_id:
        consulta = consulta.where(Empresa.responsavel_id == responsavel_id)
    ordem = func.unaccent(func.coalesce(Empresa.nome_curto, Empresa.razao_social, ""))
    return list(
        sessao.scalars(
            consulta.order_by(Empresa.ativa.desc(), ordem, Empresa.codigo_dominio, Empresa.codigo_filial.nulls_first())
        )
    )
