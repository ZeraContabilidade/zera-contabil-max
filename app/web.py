"""Ferramentas comuns das telas: modelos HTML, avisos e redirecionamentos."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import obter_config

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
}
ROTULOS_ENTIDADE = {"usuario": "Usuário"}


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
    return str(valor)


templates.env.filters["data_hora"] = _data_hora
templates.env.filters["rotulo_campo"] = _rotulo_campo
templates.env.filters["rotulo_entidade"] = _rotulo_entidade
templates.env.filters["valor_log"] = _valor_log
templates.env.globals["tirar_avisos"] = _tirar_avisos


def avisar(request: Request, texto: str, tipo: str = "ok") -> None:
    """Mensagem mostrada no topo da próxima tela (tipo 'ok' ou 'erro')."""
    request.session.setdefault("avisos", []).append({"texto": texto, "tipo": tipo})


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
