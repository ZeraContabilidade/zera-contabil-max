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
| Backup / restaurar | automático pelo `INICIAR.bat` (1 por dia) ou tela **Backup**; restaurar: `RESTAURAR.bat` (passo a passo em `docs/restaurar_backup.md`) |
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
  servicos/       regras de negócio (sem HTTP); backup.py = pg_dump pelo Docker + espelho dos arquivos + restauração
  rotas/          telas (FastAPI APIRouter)
  templates/      HTML (Jinja2); _entrada.html = moldura com o emblema; _macros.html
  static/         estilo.css (identidade Zera), tema.js, marca/ (logos, emblema, Cinzel), vendor/ (Pico, HTMX)
  ia/             cliente.py (Anthropic + falso), precos.py, servico.py (chamar_ia, limites, registro)
  leitores/       leitores de extrato como plug-ins: __init__ (tipos, ArquivoExtrato, LEITORES, ler_extrato), ferramentas.py, bb_conta_corrente.py, bb_poupanca.py, ofx.py
migracoes/      Alembic (0001 usuario+log; 0002 empresa+unaccent; 0003 conta_contabil+arquivo_original+importacao; 0004 chamada_ia; 0005 conta_chave; 0006 lancamento_historico+padrao+perfil; 0007 lançamento com um lado só; 0008 revisado_ia; 0009 conta_bancaria+extrato+movimento_extrato)
scripts/        rotinas dos .bat (instalar, iniciar + backup automático, restaurar, banco_docker, criar_env) + banco_teste e servidor_teste
docs/           passo a passo para o usuário (restaurar_backup.md)
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
- Campo preenchido pelo sistema → incluir o nome em `campos_automaticos` (selo 🤖); `aplicar_edicao` tira o selo quando o usuário muda o valor; preenchimento automático só ocupa campo vazio ou ainda automático.
- Busca de texto: `func.unaccent(coluna).ilike(func.unaccent(padrao))` (extensão criada na migração 0002).
- Mês de trabalho: `competencia_da_tela(request, mes)` (padrão mês passado; guardado na sessão).
- Barra do mês: cada etapa nova acrescenta sua conferência em `app/servicos/progresso.py::_concluidas`.
- Testes nunca acessam a internet (fixture autouse `_sem_internet`); para simular a BrasilAPI use `cnpj_responde(resposta)`.
- **Backup:** só por `app/servicos/backup.py` (`fazer_backup`, `situacao`, `restaurar_backup`). Nos testes `PASTA_BACKUP` é temporária e `PASTA_BACKUP_NUVEM=NAO` (nunca grava no Google Drive real); o servidor de teste usa `dados/backups_teste`. Tabela nova entra sozinha no backup (é o banco inteiro).
- CNPJ/CPF: sempre por `app/servicos/documentos.py` (aceita CNPJ alfanumérico de jul/2026); gravar normalizado (só letras e números).
- Importações em bloco (plano, Diário, extrato) **não** usam `Auditavel` linha a linha: gravam `ArquivoOriginal` (`guardar_arquivo`) + `Importacao` (resumo e avisos) + `registrar_evento`.
- Avisos de importação = `Aviso(texto, itens)`: texto curto com exemplos, lista completa em `itens` (a tela abre ao clicar).
- **IA:** nunca chamar o SDK direto — montar `PedidoIA` (instruções fixas, `contexto` grande e estável para o cache, `pergunta` variável, `esquema` JSON com `additionalProperties: false`, `forte=True` só quando precisa) e chamar `app.ia.servico.chamar_ia(sessao, pedido, empresa, usuario)`; capturar `ErroIA` (inclui `IAIndisponivel`) e seguir sem IA. **Validar** a resposta (conta existe e é analítica etc.) antes de gravar. Testes: fixture `ia_falsa` (`ia_falsa.respostas[finalidade] = {...}`). Modelos: Haiku 4.5 não aceita `effort`; Sonnet 5.5 não aceita `tool_choice` forçado nem `thinking` desligado. Ler a skill `claude-api` antes de mudar `app/ia/cliente.py`.
- **Contas-chave:** usar `app/servicos/contas_chave.py` — natureza das contas por `naturezas()` (pelo nome do grupo, nunca pelo número); conta bancária por `ligar_conta_bancaria()`; nunca sobrescrever origem `USUARIO`. Parâmetro de teste não pode se chamar `banco` (é o nome da fixture do PostgreSQL).
- Processo demorado (importação, IA) → `data-aguarde="texto"` no `<form>`. Envio de arquivos por arrastar → `data-arrastar` no `<form>` + `.zona-arquivos` (arrastar.js envia ao soltar ou escolher).
- **Extratos:** leitor novo = um arquivo em `app/leitores/` com `nome`, `reconhece(arquivo)` (pelo CONTEÚDO) e `ler(arquivo)` → `ExtratoLido`, registrado em `LEITORES`. PDF: ler pela posição das palavras (`arquivo.paginas`, `ferramentas.linhas`). Importação só por `app/servicos/extratos.importar_extrato` (conta bancária criada sozinha e ligada à conta-chave — reusa a que já existe, ex.: achada pelo histórico; hash anti-duplicidade por conta + dia + sentido + valor + nº da vez no dia — o texto fica de fora para o PDF e o OFX do mesmo mês não duplicarem; a mesma conta escrita de jeitos diferentes é achada por `mesma_conta` (“72637-0” = “0000726370”; agência só desempata quando os dois lados têm); sem saldo inicial (OFX) → vale o saldo final do extrato da véspera da mesma conta; conferência de saldo; saldo cortado confere até R$ 1,00). Testes de leitor de PDF montam as palavras com posição (`PdfFalso` em `tests/test_extratos.py`); na importação, `monkeypatch` em `app.servicos.extratos.ler_extrato`.
- **Aprendizado:** histórico (lanctos.txt ou Diário em Excel — `importar_historico` detecta: planilha = Diário, `app/servicos/diario.py`) → `Movimento` → `LancamentoHistorico`; o mesmo lançamento vindo dos dois arquivos é achado por lado (data, valor, histórico, D/C, conta — `_JaImportados`) e conta uma vez só (o lado que faltava é completado); padrões sempre recalculados por `aprender()` a partir de TODO o histórico (nunca editar padrão aprendido à mão no código; o usuário muda pela tela → origem `USUARIO`). Processo em bloco: `sessao.info["auditoria_em_bloco"] = True` + um `registrar_evento`. Valores monetários nos `detalhes` JSON ficam como texto `"910.00"`; na tela use o filtro `reais`.
- **IA no histórico:** `app/servicos/historico_ia.py` — `revisar_historico` pergunta em lotes o que as regras não resolveram (um lado só fora do banco → `bancario`; SAIDA/ENTRADA sem “ - ” → favorecido/CNPJ/natureza); agrupa por modelo de histórico + conta + lado; marca `revisado_ia`; CNPJ da IA só vale se estiver escrito no histórico. Roda sozinho ao importar e pelo botão “Completar com a IA”. Contas-chave pela prática da empresa: `EVIDENCIAS` em `aprendizado.py`, no fim de `aprender()` (nunca troca origem `USUARIO`).
- Plano de contas de teste comum: `tests/planos.py` (`criar_plano`). Histórico de teste anonimizado: `tests/dados/lanctos_exemplo.txt`. Diários de teste: `tests/diarios.py` (`montar_diario`, layout do Domínio, dados fictícios).
- **Chave da API:** só no `.env` (`ANTHROPIC_API_KEY`). Nunca pedir, mostrar ou registrar a chave no chat/log.
- Testes com arquivos: cópias anonimizadas em `tests/dados/`; teste com arquivo real de AMOSTRAS usa `@pytest.mark.amostras` e pula se a pasta não existir. Arquivos enviados nos testes vão para uma pasta temporária (`PASTA_ARQUIVOS_TESTE`).
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
- Para editar arquivo com `\` (caminhos do Windows) ou `\n` dentro de código, usar a ferramenta Edit — script Python em heredoc transforma `\b` e `\n` em caracteres de controle.
- O Google Drive para computador ainda **não está instalado** neste computador: o backup acha `<unidade>:\Meu Drive` sozinho quando for instalado.
- Segurança do login: cookie assinado (`CHAVE_SESSAO`), SameSite=Lax (bloqueia formulário de outro site). Antes de ir para a nuvem (Fase 4), avaliar token CSRF e HTTPS.
- O Python do computador é o 3.13 (a especificação citava 3.12; tudo é compatível).
- **Nunca editar arquivo de texto com `Get-Content`/`Set-Content` do PowerShell 5.1**: ele lê UTF-8 sem BOM como ANSI e corrompe os acentos (“Classificação” → “ClassificaÃ§Ã£o”). Usar Edit/Write ou Python com `encoding="utf-8"`.
- O navegador embutido do app não recebe cliques com a janela minimizada; para conferir telas sem ele, logar por script (`httpx2`, senha em `scripts/servidor_teste.py`) e ler o HTML.
- O Claude Code define `ANTHROPIC_BASE_URL` no ambiente desta sessão: por isso o cliente da IA passa `base_url` fixo (`ia_endereco`). Testes de IA real: `pytest -m ia_real -s` (lê a chave direto do `.env`).

## Fatos das amostras (complementam §11)
- `AMOSTRAS/PLANO DE CONTAS/contas crianca.csv` é o **TXT de largura fixa do Domínio** com extensão errada (1.190 contas) → detectar o formato pelo conteúdo, não pela extensão.
- O plano da Casa Criança tem **22 classificações usadas por 44 contas** (ex.: 492 VALE TRANSPORTE e 10585 DESPESA COM RESCISÃO = 3.2.2.01.000010) → ao converter classificação → reduzido, usar também a descrição. A conta 10598 é analítica com classificação de nível 4.
- O plano **não tem conta para a poupança BB 72637-0** (só "APLIC BB" e "APLIC BB nnnn" de outras contas).
- No TXT do Domínio a coluna 68 traz **sempre** o tipo S/A (a descrição é cortada em 40 letras, não invade o tipo). Confiar no tipo do arquivo; a hierarquia discorda em 60 contas (grupos vazios, analíticas com classificação de grupo como a 10598).
- O plano da Casa Criança repete descrições em grupos diferentes (5× “ÁGUA E ESGOTO”: 355, 10491, 10543, 10490, 10270, 10486) — o lanctos.txt usa a 355. Classificar pelo histórico da empresa, não só pela descrição.
- `AMOSTRAS/PLANO DE CONTAS/contas.txt` = plano de outra entidade (máscara 1.1.2.2.3.4, reduzidos 1000–7005) → 2º caso de teste.
- PDFs do BB foram impressos pelo navegador: **coluna Saldo cortada**; valor e C/D às vezes caem em linhas diferentes → ler pela posição das palavras. Conferência: CC entradas = saídas = 149.568,52 (saldo 0 → 0); poupança saldo anterior 227.494,23 → final 239.233,33. CC (lido, 49 movimentos): colunas x ≈ data 53 | ag 154 | lote 193 | código+histórico 225 | documento (fim 461) | valor (fim 514) + C/D 516 | saldo 560 (cortado: “0,”); 2ª linha a partir de x 225 com “dd/mm hh:mm FAVORECIDO” ou só o favorecido; o cabeçalho de colunas só existe na 1ª página. Poupança (lido, 28 movimentos): cada lançamento em até 3 linhas a ~4,8 pt da linha da data (histórico e informações começam em cima e terminam embaixo; valor e C/D podem ficar em linhas diferentes) → juntar pela proximidade (≤ 6,5 pt); colunas x ≈ dt.lanç 50 | dt.base 104 | dia 150 | histórico 171 | ag 279 | documento 317 | informações 361 | valor (fim 527) | C/D 530 | saldo 540+; saldo anterior cortado (“227.4”) → anterior calculado pelo saldo do cabeçalho (só vale se bater com o “Saldo total” cortado do fim) e conferido pelo começo (`saldo_inicial_visivel`). Códigos BB: poupança 141 Transferencia Para Conta = CC 875 Transferido da poupança; poupança 601 Transferência de Crédito = CC 475 Aplicação Poupança; 737 Juros e 741 Reajuste Monetário (créditos), 290 Imposto De Renda (débito). A variação da poupança (51) não entra no número da conta bancária. OFX: leitor próprio tolerante (`app/leitores/ofx.py`, sem `ofxtools`: os OFX brasileiros vêm em SGML sem fechar tags, cp1252 e às vezes vírgula decimal); uma conta por arquivo; cartão de crédito recusado.
- `AMOSTRAS/PLANILHA EXPORTAÇÃO/modelo exemplar da exportacao.txt` (2026, 195 linhas, com os 3 erros) e `AMOSTRAS/historicos/lanctos_2025_casa_crianca.txt` (389 linhas) vieram de `Z:\1 ASSOC CRECHES CLIENTES\230 CASA CRIANCA ESPERANCA\3 PRESTAÇÃO\<ano>\lanctos.txt`.
- De 2025 para 2026 mudou o lançamento de salários (331 despesa → 187 salários a pagar) → o aprendizado deve priorizar o mais recente. O TXT de 2025 tem CNPJ inválido (`31.599.393/000-25`).
- Macro `Gerar()` da planilha: `Print #` do VBA → Windows-1252, CRLF, valores formatados pelo Windows em pt-BR.
- `AMOSTRAS/historicos/Diário.xls` (jan–jun/2026, 417 linhas) foi impresso **só com o Passivo (grupo 2)**: os dias não fecham débito = crédito, não aparece a conta 8. Colunas A/D/F/I/N/R; “TOTAL DO DIA” e “TOTAL DO MÊS”; CNPJ do cabeçalho válido. Com o lanctos.txt de 2026: **129 linhas repetidas** (os pagamentos) e 122 novas, todas OUTRO (provisões da folha, “AQUISICAO CONFORME NOTA FISCAL”, “REPASSE MUNICIPAL” → 2.2.2.01.000005 VERBA RECEBIDA A APLICAR, “RENDIMENTO APLICAÇÃO FINANCEIRA” → 2.2.2.01.000006 RENDIMENTO A APLICAR).
