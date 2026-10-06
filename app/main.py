"""Aplicação web (FastAPI + Jinja2 + HTMX)."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import obter_config
from app.db import banco_disponivel

PASTA_APP = Path(__file__).resolve().parent

app = FastAPI(title=obter_config().nome_sistema, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=PASTA_APP / "static"), name="static")

templates = Jinja2Templates(directory=PASTA_APP / "templates")
templates.env.globals["nome_sistema"] = obter_config().nome_sistema


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    return templates.TemplateResponse(request, "inicio.html", {"banco_ok": banco_disponivel()})


@app.get("/saude")
def saude():
    """Usado pelo INICIAR.bat para saber quando o sistema está no ar."""
    return {"sistema": "ok", "banco": "ok" if banco_disponivel() else "indisponivel"}
