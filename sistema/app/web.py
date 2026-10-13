"""Ferramentas comuns das telas: modelos HTML, avisos e redirecionamentos."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import obter_config
from app.ia.servico import dolar
from app.servicos.competencia import Periodo, ler_periodo, mes_anterior, nome_competencia, valor_campo_mes
from app.servicos.documentos import formatar_documento

FUSO = ZoneInfo("America/Sao_Paulo")
PASTA_APP = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=PASTA_APP / "templates")
templates.env.globals["nome_sistema"] = obter_config().nome_sistema


def _estatico(caminho: str) -> str:
    """Endereço do CSS/JS/imagem com a versão do arquivo: depois de uma atualização
    o navegador baixa o arquivo novo em vez de usar o guardado (cache)."""
    try:
        versao = int((PASTA_APP / "static" / caminho).stat().st_mtime)
    except OSError:
        versao = 0
    return f"/static/{caminho}?v={versao}"


templates.env.globals["estatico"] = _estatico


def _data_hora(valor: datetime | None) -> str:
    return valor.astimezone(FUSO).strftime("%d/%m/%Y %H:%M") if valor else "—"


def _tirar_avisos(request: Request) -> list[dict]:
    return request.session.pop("avisos", [])


# nomes dos campos e tabelas como aparecem no log (o que não estiver aqui vira "Nome do campo")
ROTULOS_CAMPO = {
    "login": "Usuário",
    "email": "E-mail",
    "senha_hash": "Senha",
    "criado_em": "Criado em",
    "codigo_dominio": "Código no Domínio",
    "codigo_filial": "Código da filial",
    "razao_social": "Razão social",
    "cnpj_cpf": "CNPJ/CPF",
    "responsavel_id": "Responsável (nº do usuário)",
    "observacoes": "Observações",
    "modelo_complemento": "Modelo do complemento",
    "ativa": "Ativa",
    "usa_conta_individual": "Conta individual por fornecedor",
    "grupo_fornecedores": "Grupo dos fornecedores",
    "ia_ligada": "IA ligada",
    "ia_limite_mensal_usd": "Limite mensal de IA (US$)",
    "conta_id": "Conta (nº interno)",
    "confianca": "Confiança (%)",
}
ROTULOS_ENTIDADE = {
    "usuario": "Usuário",
    "empresa": "Empresa",
    "conta_chave": "Conta-chave",
    "padrao": "Padrão aprendido",
    "conta_bancaria": "Conta bancária",
    "modelo_planilha_banco": "Modelo de planilha de extrato",
    "sugestao": "Sugestão de lançamento",
}


def _rotulo_campo(campo: str) -> str:
    return ROTULOS_CAMPO.get(campo, campo.replace("_", " ").capitalize())


def _rotulo_entidade(entidade: str) -> str:
    return ROTULOS_ENTIDADE.get(entidade, entidade.replace("_", " ").capitalize())


def _valor_log(valor) -> str:
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, str) and len(valor) >= 19 and valor[4] == "-" and valor[10] == "T":
        try:
            return _data_hora(datetime.fromisoformat(valor))
        except ValueError:
            pass
    if isinstance(valor, str) and len(valor) == 10 and valor[4] == "-" and valor[7] == "-":
        try:
            return date.fromisoformat(valor).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return str(valor)


templates.env.filters["data_hora"] = _data_hora
templates.env.filters["rotulo_campo"] = _rotulo_campo
templates.env.filters["rotulo_entidade"] = _rotulo_entidade
templates.env.filters["valor_log"] = _valor_log
templates.env.filters["milhar"] = lambda n: f"{n or 0:,}".replace(",", ".")
templates.env.filters["reais"] = lambda v: (
    f"{Decimal(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
)
templates.env.filters["documento"] = formatar_documento
templates.env.filters["dolar"] = lambda valor, casas=2: dolar(Decimal(valor or 0), casas)
templates.env.filters["tamanho"] = lambda n: (
    f"{n / 1024 / 1024:.1f} MB".replace(".", ",") if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"
)
templates.env.filters["nome_competencia"] = nome_competencia
templates.env.filters["valor_campo_mes"] = valor_campo_mes
templates.env.globals["tirar_avisos"] = _tirar_avisos


def saudacao(agora: datetime | None = None) -> str:
    """“Bom dia”, “Boa tarde” ou “Boa noite”, pelo relógio de São Paulo."""
    hora = (agora or datetime.now(FUSO)).hour
    return "Bom dia" if 5 <= hora < 12 else "Boa tarde" if 12 <= hora < 18 else "Boa noite"


templates.env.globals["saudacao"] = saudacao


def avisar(request: Request, texto: str, tipo: str = "ok") -> None:
    """Mensagem mostrada na próxima tela (tipo 'ok', 'atencao', 'erro' ou 'festa' — conquista, com confete)."""
    request.session.setdefault("avisos", []).append({"texto": texto, "tipo": tipo})


def competencia_da_tela(request: Request, mes: str | None, ate: str | None = None) -> Periodo:
    """Mês ou período escolhido na tela (“mes” sozinho, “mes” + “ate”, ou “2025-01_2025-12” vindo de um endereço);
    fica guardado para as próximas telas. Padrão: o mês passado."""
    periodo = ler_periodo(mes, ate) or ler_periodo(request.session.get("competencia")) or Periodo.do_mes(mes_anterior())
    request.session["competencia"] = valor_campo_mes(periodo)
    return periodo


def pagina(request: Request, nome: str, status_code: int = 200, **contexto):
    contexto.setdefault("usuario", getattr(request.state, "usuario", None))
    return templates.TemplateResponse(request, nome, contexto, status_code=status_code)


def redirecionar(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def destino_seguro(url: str | None) -> str:
    """Só aceita endereços deste sistema (evita mandar o usuário para outro site)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/"
