"""Busca rápida (Ctrl+K): a lista do que dá para abrir de qualquer tela — cada empresa já no próximo passo do mês,
as abas de cada empresa e as telas do sistema. A filtragem é feita no navegador (static/paleta.js)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import usuario_logado
from app.db import obter_sessao
from app.modelos import Usuario
from app.servicos.empresas import buscar_empresas
from app.servicos.progresso import etapa_atual, progresso_do_mes
from app.web import competencia_da_tela

router = APIRouter()

ABA_DA_ETAPA = {
    "plano": "plano",
    "aprendizado": "aprendizado",
    "extrato": "extratos",
    "revisao": "revisao",
    "exportado": "exportar",
}
ABAS = [  # (aba, nome, ícone) — na ordem do mês; o cadastro por último
    ("plano", "Plano de contas", "plano"),
    ("aprendizado", "Aprendizado", "aprendizado"),
    ("extratos", "Extratos", "extratos"),
    ("revisao", "Revisão", "revisao"),
    ("exportar", "Exportar", "exportar"),
    ("cadastro", "Cadastro", "cadastro"),
]
TELAS = [  # (nome, endereço, ícone, só o Supervisor, palavras que também acham)
    ("Empresas", "/", "empresas", False, "inicio mesa de trabalho"),
    ("Painel do Supervisor", "/painel", "painel", True, "todas as empresas pendencias"),
    ("Nova empresa", "/empresas/nova", "mais", True, "cadastrar cliente"),
    ("IA — uso e custo", "/ia", "ia", True, "inteligencia artificial gasto"),
    ("Backup", "/backup", "nuvem", True, "copia de seguranca restaurar google drive"),
    ("Usuários", "/usuarios", "usuarios", True, "senha acesso equipe"),
    ("Log", "/log", "log", True, "historico auditoria quem fez"),
    ("Minha senha", "/minha-senha", "cadastro", False, "trocar senha"),
]


@router.get("/atalhos")
def atalhos(
    request: Request,
    usuario: Usuario = Depends(usuario_logado),
    sessao: Session = Depends(obter_sessao),
) -> dict:
    periodo = competencia_da_tela(request, None)
    empresas = []
    for empresa in buscar_empresas(sessao):
        if not empresa.ativa:
            continue
        atual = etapa_atual(progresso_do_mes(sessao, empresa, periodo))
        detalhe = f"código {empresa.rotulo_codigo}"
        if empresa.documento_formatado:
            detalhe += f" · {empresa.documento_formatado}"
        empresas.append(
            {
                "id": empresa.id,
                "nome": empresa.nome,
                "outro_nome": empresa.razao_social if empresa.nome_curto else "",
                "detalhe": detalhe,
                "proximo": f"Próximo: {atual.nome}" if atual else "Período concluído",
                "aba": ABA_DA_ETAPA[atual.chave] if atual else "exportar",
            }
        )
    telas = [
        {"nome": nome, "url": url, "icone": icone, "palavras": palavras}
        for nome, url, icone, so_supervisor, palavras in TELAS
        if usuario.e_supervisor or not so_supervisor
    ]
    abas = [{"aba": aba, "nome": nome, "icone": icone} for aba, nome, icone in ABAS]
    return {"empresas": empresas, "abas": abas, "telas": telas}
