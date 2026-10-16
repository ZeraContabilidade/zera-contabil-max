"""Pasta de entrada: o sistema busca sozinho os extratos novos na pasta onde o cliente os deixa (ex.: no Z:\\),
inclusive nas subpastas dos meses (“EXTRATOS 2026\\1. JANEIRO”). Só LÊ — nunca altera, move ou apaga nada lá.

- Cada arquivo olhado fica anotado (`ArquivoPasta`): a próxima busca pula o que não mudou (caminho, tamanho e data)
  sem nem abrir, e não repete o mesmo aviso. Cópias (“Extrato (1).ofx”) são achadas pelo conteúdo (SHA-256).
- OFX primeiro, PDF depois. Arquivo que não traz nenhum movimento novo (o PDF do mesmo mês que o OFX já trouxe, ou o
  mesmo extrato baixado de novo) NÃO vira mais um extrato na lista: fica anotado como “igual”.
- PDF de banco sem leitor próprio NÃO vai para a IA aqui (custo sem ninguém ver): fica listado para mandar pela tela.
- O demonstrativo da prestação de contas (Excel com o “BLOCO 4 - PAGAMENTOS EFETUADOS”) é lido sozinho, depois dos
  extratos (15/10/2026). As outras planilhas não — na pasta do cliente costumam ser outras coisas; mande pela tela.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.leitores import NaoReconhecido
from app.leitores.demonstrativo import e_demonstrativo
from app.modelos import ArquivoOriginal, ArquivoPasta, Empresa, Extrato, Importacao, Usuario
from app.servicos.demonstrativos import importar_demonstrativo
from app.servicos.exportacao_automatica import meses_entre
from app.servicos.extratos import importar_extrato
from app.servicos.plano import ErroLeitura

ORDEM = {".ofx": 0, ".pdf": 1}  # lidos sozinhos, nesta ordem
PLANILHAS = {".xlsx", ".xls", ".csv"}  # anotadas, mas não lidas sozinhas
TAMANHO_MAXIMO = 30 * 1024 * 1024
JA_RESOLVIDOS = ("LIDO", "IGUAL", "SEM_LEITOR", "PLANILHA")  # ERRO é tentado de novo


class PastaInvalida(Exception):
    """A pasta do cadastro não existe ou não está acessível agora."""


@dataclass
class ResultadoPasta:
    lidos: list[tuple[str, Extrato]] = field(default_factory=list)
    demonstrativos: list[tuple[str, Importacao]] = field(default_factory=list)
    ja_lidos: int = 0  # sem mudança desde a última busca, cópia, ou nada novo
    sem_leitor: list[str] = field(default_factory=list)
    planilhas: list[str] = field(default_factory=list)
    erros: list[tuple[str, str]] = field(default_factory=list)

    @property
    def meses(self) -> set[date]:
        meses = {mes for _, extrato in self.lidos for mes in meses_entre(extrato.inicio, extrato.fim)}
        return meses | {date.fromisoformat(i.resumo["mes"]) for _, i in self.demonstrativos}

    @property
    def novos(self) -> int:
        return sum(extrato.importacao.resumo.get("novos", 0) for _, extrato in self.lidos)

    def resumo(self) -> str:
        if not self.lidos and not self.demonstrativos:
            return f"Pasta do cliente: nenhum extrato novo ({self.ja_lidos} arquivo(s) já estavam no sistema)."
        texto = f"Pasta do cliente: {len(self.lidos)} extrato(s) lido(s) com {self.novos} movimento(s) novo(s)"
        if self.demonstrativos:
            texto += f", {len(self.demonstrativos)} demonstrativo(s)"
        if self.ja_lidos:
            texto += f", {self.ja_lidos} já estavam no sistema"
        return texto + "."


def arquivos_da_pasta(pasta: Path) -> list[Path]:
    if not pasta.is_dir():
        raise PastaInvalida(
            f"Não encontrei a pasta “{pasta}”. Confira o caminho no Cadastro da empresa e se o Z:\\ (ou a rede) está "
            "conectado neste computador."
        )
    arquivos = [
        caminho
        for caminho in pasta.rglob("*")
        if caminho.suffix.lower() in ORDEM.keys() | PLANILHAS
        and not caminho.name.startswith(("~$", "."))
        and caminho.is_file()
    ]
    return sorted(arquivos, key=lambda c: (ORDEM.get(c.suffix.lower(), 9), str(c).lower()))


def nao_lidos_sozinhos(sessao: Session, empresa: Empresa) -> list[ArquivoPasta]:
    """PDFs sem leitor próprio e planilhas que a busca achou e deixou para mandar pela tela."""
    return list(
        sessao.scalars(
            select(ArquivoPasta)
            .where(ArquivoPasta.empresa_id == empresa.id, ArquivoPasta.resultado.in_(("SEM_LEITOR", "PLANILHA")))
            .order_by(ArquivoPasta.caminho)
        )
    )


def buscar_na_pasta(sessao: Session, empresa: Empresa, usuario: Usuario | None) -> ResultadoPasta:
    """Lê os extratos novos da pasta do cliente. Quem chama faz o commit (cada arquivo entra num ponto de salvamento:
    um arquivo com problema não desfaz os outros)."""
    if not empresa.pasta_extratos:
        raise PastaInvalida("Informe no Cadastro da empresa a pasta onde o cliente deixa os extratos.")
    pasta = Path(empresa.pasta_extratos)
    arquivos = arquivos_da_pasta(pasta)
    anotados = {a.caminho: a for a in sessao.scalars(select(ArquivoPasta).where(ArquivoPasta.empresa_id == empresa.id))}
    conhecidos = {a.sha256 for a in anotados.values() if a.resultado in JA_RESOLVIDOS}
    conhecidos |= set(
        sessao.scalars(
            select(ArquivoOriginal.sha256).where(
                ArquivoOriginal.empresa_id == empresa.id, ArquivoOriginal.tipo == "EXTRATO"
            )
        )
    )
    resultado = ResultadoPasta()
    for caminho in arquivos:
        nome, chave = caminho.name, str(caminho.relative_to(pasta))
        try:
            info = caminho.stat()
        except OSError as erro:
            resultado.erros.append((nome, f"não consegui abrir ({erro.strerror or erro})"))
            continue
        modificado = datetime.fromtimestamp(int(info.st_mtime), UTC)
        anotado = anotados.get(chave)
        if (
            anotado is not None
            and anotado.resultado != "ERRO"
            and (anotado.tamanho, anotado.modificado_em) == (info.st_size, modificado)
        ):
            resultado.ja_lidos += 1  # nada mudou desde a última busca: nem abre
            continue
        situacao, detalhe, impressao = _olhar(sessao, empresa, usuario, caminho, info.st_size, conhecidos, resultado)
        if anotado is None:
            anotado = ArquivoPasta(empresa_id=empresa.id, caminho=chave[:500])
            sessao.add(anotado)
            anotados[chave] = anotado
        anotado.tamanho, anotado.modificado_em, anotado.sha256 = info.st_size, modificado, impressao
        anotado.resultado, anotado.detalhe = situacao, detalhe
    sessao.flush()
    return resultado


def _olhar(sessao, empresa, usuario, caminho: Path, tamanho: int, conhecidos: set[str], resultado: ResultadoPasta):
    """Abre um arquivo novo (ou que mudou) e decide o que fazer. Devolve (situação, detalhe, SHA-256)."""
    nome = caminho.name
    if tamanho > TAMANHO_MAXIMO:
        resultado.erros.append((nome, "passa de 30 MB"))
        return "ERRO", "passa de 30 MB", ""
    try:
        conteudo = caminho.read_bytes()
    except OSError as erro:
        motivo = f"não consegui abrir ({erro.strerror or erro})"
        resultado.erros.append((nome, motivo))
        return "ERRO", motivo, ""
    impressao = hashlib.sha256(conteudo).hexdigest()
    if impressao in conhecidos:
        resultado.ja_lidos += 1
        return "IGUAL", "o mesmo conteúdo já tinha entrado", impressao
    conhecidos.add(impressao)
    if caminho.suffix.lower() in PLANILHAS and e_demonstrativo(conteudo):
        ponto = sessao.begin_nested()
        try:
            importacao = importar_demonstrativo(sessao, empresa, nome, conteudo, usuario)
        except ErroLeitura as erro:
            ponto.rollback()
            resultado.erros.append((nome, str(erro)))
            return "ERRO", str(erro)[:2000], impressao
        ponto.commit()
        resultado.demonstrativos.append((nome, importacao))
        return "LIDO", f"demonstrativo de {importacao.resumo['mes'][:7]}", impressao
    if caminho.suffix.lower() in PLANILHAS:
        resultado.planilhas.append(nome)
        return "PLANILHA", "planilha: se for extrato, mande pela tela", impressao
    ponto = sessao.begin_nested()
    try:
        extrato = importar_extrato(sessao, empresa, nome, conteudo, usuario, usar_ia=False)
    except NaoReconhecido:
        ponto.rollback()
        resultado.sem_leitor.append(nome)
        return "SEM_LEITOR", "banco sem leitor próprio: a IA lê se você mandar pela tela", impressao
    except ErroLeitura as erro:
        ponto.rollback()
        resultado.erros.append((nome, str(erro)))
        return "ERRO", str(erro)[:2000], impressao
    if not extrato.importacao.resumo.get("novos"):
        ponto.rollback()  # nada novo (ex.: o PDF do que o OFX trouxe): não vira mais um extrato na lista
        resultado.ja_lidos += 1
        return "IGUAL", "nenhum movimento novo", impressao
    ponto.commit()
    resultado.lidos.append((nome, extrato))
    return "LIDO", None, impressao
