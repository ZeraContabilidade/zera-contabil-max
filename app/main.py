"""Aplicação web (FastAPI + Jinja2 + HTMX)."""

import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from starlette.middleware.sessions import SessionMiddleware

from app.auth import NaoAutenticado, SemPermissao
from app.config import obter_config
from app.db import banco_disponivel
from app.rotas import acesso, empresas, ia, plano, usuarios
from app.web import pagina, redirecionar

PASTA_APP = Path(__file__).resolve().parent
config = obter_config()

app = FastAPI(title=config.nome_sistema, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.chave_sessao or secrets.token_urlsafe(32),
    session_cookie="zcm_sessao",
    max_age=12 * 60 * 60,  # um dia de trabalho
    same_site="lax",  # formulários de outros sites não conseguem usar o login
)
app.mount("/static", StaticFiles(directory=PASTA_APP / "static"), name="static")
app.include_router(acesso.router)
app.include_router(empresas.router)
app.include_router(plano.router)
app.include_router(ia.router)
app.include_router(usuarios.router)


@app.exception_handler(NaoAutenticado)
def _ir_para_login(request: Request, _erro: NaoAutenticado):
    destino = "/login"
    if request.url.path not in ("/", "/login"):
        destino += "?proximo=" + quote(request.url.path)
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": destino})
    return redirecionar(destino)


@app.exception_handler(SemPermissao)
def _sem_permissao(request: Request, erro: SemPermissao):
    return pagina(request, "erro.html", status_code=403, titulo="Sem permissão", mensagem=str(erro))


@app.exception_handler(OperationalError)
def _banco_fora(request: Request, _erro: OperationalError):
    return pagina(
        request,
        "erro.html",
        status_code=503,
        titulo="Banco de dados desligado",
        mensagem="Feche esta janela e abra o sistema de novo pelo INICIAR.bat "
        "(ele liga o Docker e o banco de dados sozinho).",
    )


@app.get("/saude")
def saude():
    """Usado pelo INICIAR.bat para saber quando o sistema está no ar."""
    return {"sistema": "ok", "banco": "ok" if banco_disponivel() else "indisponivel"}
