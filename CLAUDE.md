# ZERA CONTÁBIL MAX — guia para o Claude Code

**Ao começar uma sessão:** leia este arquivo e o `PROGRESSO.md` e continue do "Próximo passo exato".
A especificação completa está em `PROMPT_Claude_Code_ZeraConcilia.md` (citada aqui como §).

## Regras do projeto
- **Português do Brasil** em tudo: telas, mensagens e nomes do domínio no código. Mensagem de erro diz **o que fazer**.
- O usuário é contador(a), não programador(a): explicar resultados e testes em linguagem simples.
- **Etapas pequenas** (plano Claude Pro tem limite): cada etapa termina com `pytest` + `ruff` passando, commit e `PROGRESSO.md` atualizado.
- Dinheiro sempre `Decimal`, nunca `float`.
- Nenhum caminho fixo de Windows no código do sistema: tudo vem do `.env` via `app/config.py`.
- Não inventar formatos: §11 é a especificação. A IA só pode sugerir contas **existentes e analíticas**.
- Teste falhando → corrigir a causa, nunca apagar o teste.
- `AMOSTRAS/`, `.env` e `dados/` ficam fora do Git. Testes usam cópias **anonimizadas** em `tests/dados/`.
- O drive `Z:\` (servidor do escritório) é **só leitura**.

## Comandos
| O quê | Como |
|---|---|
| Instalar / atualizar dependências | `INSTALAR.bat` (cria `.venv`, instala `requirements.txt`, cria `.env` com senhas, sobe o PostgreSQL) |
| Iniciar | `INICIAR.bat` → abre http://localhost:8000 (`INICIAR.bat --sem-navegador` para testes) |
| Testes | `.venv\Scripts\python -m pytest` (marcados `banco` pulam se o PostgreSQL estiver desligado; `-m ia_real` usa a API real) |
| Qualidade | `.venv\Scripts\python -m ruff check .` e `.venv\Scripts\python -m ruff format .` |
| Banco | `docker compose up -d banco` · contêiner `zera-contabil-max-banco` · porta `127.0.0.1:5433` |
| Nova migração | `.venv\Scripts\alembic revision --autogenerate -m "descricao" --rev-id 0002` → revisar o arquivo (Enum gera CHECK em dobro: apagar o explícito) |
| Ver as telas | `.venv\Scripts\python -m scripts.servidor_teste` → http://127.0.0.1:8001 (banco `_teste`, usuários ana/carla/davi; senha em `scripts/servidor_teste.py`). Também em `.claude/launch.json` (`zera-teste`). Rodar o pytest apaga esses dados: reinicie o servidor. |

## Estrutura
```
app/            sistema web
  config.py       configurações do .env
  db.py           conexão, sessão por requisição, migrações (e liga a auditoria)
  auth.py         senhas (argon2), login por sessão, usuario_logado / exigir_supervisor
  auditoria.py    log automático de CRIAR/ALTERAR/EXCLUIR de todo modelo Auditavel
  web.py          templates, avisar(), pagina(), estatico() (CSS/JS com ?v= contra cache velho)
  modelos/        tabelas (SQLAlchemy) — importar tudo por app.modelos
  servicos/       regras de negócio (sem HTTP)
  rotas/          telas (FastAPI APIRouter)
  templates/      HTML (Jinja2); _entrada.html = moldura com o emblema; _macros.html
  static/         estilo.css (identidade Zera), tema.js, marca/ (logos, emblema, Cinzel), vendor/ (Pico, HTMX)
migracoes/      Alembic (0001 = usuario + log)
scripts/        rotinas dos .bat (instalar, iniciar, banco_docker, criar_env) + banco_teste e servidor_teste
tests/          pytest (banco separado <nome>_teste)
ferramentas/preparar_computador/   instalador da máquina (Git, Python, Node, Docker, Claude Code)
AMOSTRAS/       arquivos reais da Casa Criança (fora do Git)
```

## Convenções do código
- Modelo novo que guarda dados do escritório → herdar `Auditavel` (o log de auditoria sai sozinho; campos sigilosos em `campos_sigilosos`).
- Tela nova que exige login → `Depends(usuario_logado)`; só Supervisor → `Depends(exigir_supervisor)`.
- Mensagem para a próxima tela → `avisar(request, "texto", "ok"|"erro")`; formulário com erro → renderiza de novo com status 400 e a lista `erros`.
- Formulários usam `Form("")` e validam na mão (mensagens em português), nunca o erro 422 automático.
- Arquivos estáticos nos templates sempre por `estatico('caminho')`.
- Ao ver telas, usar o servidor de teste + Playwright (`browser_take_screenshot`); o painel do app não desenha com a janela minimizada.

## Identidade visual Zera (obrigatória em todas as telas)
- Logos oficiais em `app/static/marca/` (copiadas de `Desktop\PrestacaoContas\PREVIA DA NOVA LOGO\`): `logo_escuro.png` (fundo escuro), `logo_claro.png` (fundo claro), `emblema.png` (círculo, usado na tela de entrada e como ícone). Z e E ligados pela base; R sem base; A sem travessão — **não redesenhar, usar os PNGs**.
- Paleta e fonte iguais às do PrestacaoContas (`prestacao/web/estilo.css`): fundo `#0A0A0B`, dourado `#C9A662` (claro `#A8843F`), degradê `--grad-ouro`, títulos em **Cinzel**, texto em Segoe UI.
- Escuro por padrão; claro quando o Windows pede ou pelo botão ◐ (guardado no navegador). Off-white `#F6F3EC` no modo claro.
- Botão principal = degradê dourado com texto escuro `#141107` (branco fica ilegível no dourado claro).

## Armadilhas já conhecidas (Windows)
- Conexões internas usam `127.0.0.1`, não `localhost` (o Windows tenta IPv6 antes e perde ~2 s).
- Porta fechada no Windows só responde "recusado" após ~2 s → usar timeout curto nas checagens.
- `.bat` só com ASCII e quebra de linha CRLF (o `.gitattributes` garante no Git).
- Não trocar `POSTGRES_PASSWORD` no `.env` depois que o banco foi criado (o volume guarda a senha antiga).
- TestClient da Starlette: usar `httpx2` (o `httpx` gera aviso de descontinuação).
- Jinja escapa `'` como `&#39;`: nas mensagens use aspas tipográficas “assim”.
- Segurança do login: cookie assinado (`CHAVE_SESSAO`), SameSite=Lax (bloqueia formulário de outro site). Antes de ir para a nuvem (Fase 4), avaliar token CSRF e HTTPS.
- O Python do computador é o 3.13 (a especificação citava 3.12; tudo é compatível).

## Fatos das amostras (complementam §11)
- `AMOSTRAS/PLANO DE CONTAS/contas crianca.csv` é o **TXT de largura fixa do Domínio** com extensão errada (1.190 contas) → detectar o formato pelo conteúdo, não pela extensão.
- O plano da Casa Criança tem **44 classificações repetidas** (ex.: 492 VALE TRANSPORTE e 10585 DESPESA COM RESCISÃO = 3.2.2.01.000010) → ao converter classificação → reduzido, usar também a descrição. A conta 10598 é analítica com classificação de nível 4.
- O plano **não tem conta para a poupança BB 72637-0** (só "APLIC BB" e "APLIC BB nnnn" de outras contas).
- `AMOSTRAS/PLANO DE CONTAS/contas.txt` = plano de outra entidade (máscara 1.1.2.2.3.4, reduzidos 1000–7005) → 2º caso de teste.
- PDFs do BB foram impressos pelo navegador: **coluna Saldo cortada**; valor e C/D às vezes caem em linhas diferentes → ler pela posição das palavras. Conferência: CC entradas = saídas = 149.568,52 (saldo 0 → 0); poupança saldo anterior 227.494,23 → final 239.233,33.
- `AMOSTRAS/PLANILHA EXPORTAÇÃO/modelo exemplar da exportacao.txt` (2026, 195 linhas, com os 3 erros) e `AMOSTRAS/historicos/lanctos_2025_casa_crianca.txt` (389 linhas) vieram de `Z:\1 ASSOC CRECHES CLIENTES\230 CASA CRIANCA ESPERANCA\3 PRESTAÇÃO\<ano>\lanctos.txt`.
- De 2025 para 2026 mudou o lançamento de salários (331 despesa → 187 salários a pagar) → o aprendizado deve priorizar o mais recente. O TXT de 2025 tem CNPJ inválido (`31.599.393/000-25`).
- Macro `Gerar()` da planilha: `Print #` do VBA → Windows-1252, CRLF, valores formatados pelo Windows em pt-BR.
