# PROGRESSO — ZERA CONTÁBIL MAX

Atualizado em: **06/10/2026**

## Próximo passo exato
**Etapa 1.6 — Auto-configuração das contas-chave + conta individual por fornecedor** (§3.2.1): tabela `conta_chave` (empresa, tipo BANCO/POUPANCA/APLICACAO/RENDIMENTO/IR_RETIDO/TARIFA/IOF/JUROS_PAGOS/FORNECEDOR_GENERICO/CLIENTE_GENERICO/SALARIOS/FGTS/INSS..., referência opcional banco+agência+conta, conta_contabil, origem REGRA/IA/USUARIO, confiança, justificativa) — migração `0005`. 1º **regras** (palavras e números nas descrições das analíticas: “BCO BRASIL CC 72637-0” → banco BB c/c 72637-0; “TARIFA BANCÁRIA”; “IRRF A RECUPERAR”; “RENDIMENTOS”...), depois **IA** (modelo forte, `app.ia.servico.chamar_ia`, plano analítico no `contexto` cacheado) para o que ficou incerto, devolvendo `{tipo, conta_reduzida, confianca, justificativa}`; **validar** (conta existe, é analítica) antes de gravar; confiança alta → aplicado com selo 🤖; baixa/inexistente → um aviso (“Não encontrei conta para a poupança do BB — crie no Domínio e reimporte, ou escolha”). Detecção de **conta individual por fornecedor** (grupo Fornecedores com muitas analíticas com nome de empresa → `empresa.usa_conta_individual`) e contas genéricas. Roda sozinho após importar o plano (e de novo quando um extrato de banco novo chegar — Fase 2). Tela: aba Cadastro ou nova seção “Contas-chave” com o resultado e opção de trocar. Testes com cliente falso; `ia_real` opcional. Lembrar: a Casa Criança **não tem conta da poupança 72637-0** (pergunta 5 ao usuário).

## Pendências com o usuário
| # | Pergunta | Precisa até |
|---|---|---|
| 1 | Destino do backup — o Google Drive para computador **não está instalado**; o Z:\ está disponível. Recomendado: os dois. | Etapa 1.9 |
| 2 | ~~Chave da API~~ — o usuário tem a chave (06/10). **Falta colar** em `ANTHROPIC_API_KEY=` no `.env` e testar em **IA → Testar conexão** (ou `pytest -m ia_real -s`). Nunca pedir a chave no chat. | Etapa 1.6 |
| 3 | Limite mensal de IA: adotado o padrão **US$ 20** (`IA_LIMITE_MENSAL_USD`) até o usuário dizer outro valor | — |
| 4 | **Diário.xls** da Casa Criança (jan–ago/2026) em `AMOSTRAS\historicos` | Etapa 1.7 |
| 5 | Como a poupança BB 72637-0 é lançada hoje (conta própria ou tudo na conta 8)? Talvez o Diário responda. | Etapa 1.6 |

## Plano (Fase 0 aprovada em 06/10/2026)

### Fase 1 — Base e Aprendizado
- [x] 1.1 Estrutura do projeto, PostgreSQL no Docker, INSTALAR.bat / INICIAR.bat, CLAUDE.md, PROGRESSO.md
- [x] 1.2 Banco de dados, login, papéis e log de auditoria (+ identidade visual Zera)
- [x] 1.3 Cadastro de empresas e barra de progresso do mês
- [x] 1.4 Importação do plano de contas (TXT/Excel/CSV), avisos, reimportação, copiar de outra empresa
- [x] 1.5 Módulo de IA: cliente real + falso, limites de gasto, registro de custo
- [ ] 1.6 Auto-configuração das contas-chave + detecção de conta individual por fornecedor
- [ ] 1.7 Importação do Diário: CNPJ / favorecido / natureza (regras + IA); cadastro preenchido sozinho
- [ ] 1.8 Listas de fornecedores, clientes e palavras-chave; perfil da empresa; aprendizado inicial com os lanctos.txt de 2025 e 2026
- [ ] 1.9 Backup automático + RESTAURAR.bat

### Fase 2 — Extratos e Revisão
- [ ] 2.1 Arrastar e soltar, detecção automática, anti-duplicidade, guarda do original
- [ ] 2.2 Leitor OFX
- [ ] 2.3 Leitor PDF BB conta corrente
- [ ] 2.4 Leitor PDF BB poupança
- [ ] 2.5 Leitor universal com IA (PDF) + Excel/CSV com colunas identificadas pela IA
- [ ] 2.6 Motor de classificação (regras, CNPJ, nome parecido, palavra-chave, valor) + pareamento de transferências
- [ ] 2.7 IA em lote + validação + aprovação automática dos verdes
- [ ] 2.8 Tela de Revisão + fornecedores a cadastrar; medir ≥ 85% nos 2 PDFs

### Fase 3 — Exportação e Painel
- [ ] 3.1 lanctos.txt + validações + resumo Excel + teste "arquivo de ouro"
- [ ] 3.2 Travamento e reabertura pelo Supervisor
- [ ] 3.3 Painel do supervisor + painel de uso da IA
- [ ] 3.4 Guarda de arquivos por 5 anos + acesso pela rede

### Fase 4 — Extras (um por vez, quando pedido)

## Histórico

### 06/10/2026 — Etapa 1.5 concluída
- Pacote `app/ia/` isolado: `cliente.py` (PedidoIA → RespostaIA; `ClienteAnthropic` com SDK oficial `anthropic` 1.11 e `ClienteFalso` com respostas gravadas), `precos.py` (custo estimado em Decimal), `servico.py` (`chamar_ia`: confere chave, IA da empresa e limites; registra cada chamada).
- **Resposta sempre em JSON válido** por saída estruturada (`output_config.format` + JSON Schema) — o Sonnet 5.5 não aceita “forçar ferramenta”. Instruções + contexto (plano/perfil) marcados para **cache de prompt**. No modelo forte, **substituto automático em caso de recusa** (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`); recusa/corte/JSON inválido viram erro explicado.
- Modelos no `.env`: rápido `claude-haiku-4-5` (lotes), forte `claude-sonnet-5-5` (configuração, PDF, casos difíceis) — famílias pedidas na especificação. Endereço da API **fixo** (`ia_endereco`): a `ANTHROPIC_BASE_URL` que o Claude Code define neste computador não desvia as chamadas.
- Tabela `chamada_ia` (migração 0004): toda chamada — inclusive as que falham — com tokens, custo estimado, duração, request id, começo da pergunta e resposta; gravada em sessão própria (o gasto fica registrado mesmo se a tela desistir).
- **Limites:** geral `IA_LIMITE_MENSAL_USD` (padrão US$ 20) e por empresa (cadastro); IA liga/desliga por empresa (padrão ligada). Sem chave / limite atingido → `IAIndisponivel` e o sistema segue só com regras.
- Tela **IA** (Supervisor): situação, gasto do mês × limite, gasto por empresa, últimas 50 chamadas, botão **Testar conexão com a IA** (fração de centavo) e passo a passo para colar a chave.
- `INSTALAR.bat` agora **completa o `.env`** com configurações novas sem mexer nas existentes (acrescentou `ANTHROPIC_API_KEY=` em branco, modelos e limite).
- Testes nunca usam a chave real (`ANTHROPIC_API_KEY=""` no conftest; fixture `ia_falsa`). `pytest -m ia_real -s` testa os dois modelos de verdade (pula sem chave). Servidor de teste usa IA simulada (custo zero).
- 131 testes passando; ruff limpo. Banco real: versão 0004.
- **Como testar:** abra o `.env` no Bloco de Notas → cole a chave depois de `ANTHROPIC_API_KEY=` → salve → reabra pelo `INICIAR.bat` → menu **IA** → **Testar conexão com a IA**.

### 06/10/2026 — Etapa 1.4 concluída
- Tabelas `conta_contabil`, `arquivo_original` e `importacao` (migração 0003). Arquivo original guardado por SHA-256 em `PASTA_ARQUIVOS` (5 anos; mesmo arquivo 2× ocupa espaço 1×) — `ArmazenamentoLocal`, pronto para trocar por Supabase.
- Leitor do plano: **TXT do Domínio reconhecido pelo conteúdo** (a amostra .csv é TXT), Excel (xls/xlsx/ods via calamine, título pode estar acima do cabeçalho) e CSV (; , ou tab). Tipo S/A vem do arquivo (a hierarquia erraria em 60 contas da Casa Criança); hierarquia só quando o tipo falta. Máscara deduzida (Casa Criança 1.1.1.2.6; outra entidade 1.1.2.2.3.4).
- Avisos agrupados, com a lista completa ao clicar: classificações repetidas (Casa Criança: **22 classificações usadas por 44 contas** — na Fase 0 foi dito “44 classificações”, o certo é 22), descrições de 40 letras (limite do Domínio), contas fora da máscara, tipo deduzido, reduzido repetido, linhas ignoradas.
- Reimportar casa pelo reduzido: atualiza, acrescenta, **desativa (não apaga)** as que sumiram e reativa se voltarem. Copiar plano de outra empresa. Cada importação fica no log.
- Aba “2 Plano de Contas”: resumo, avisos, busca instantânea sem acento (“agua”, “355”, “3.2.2.04”), “Só analíticas”, contas recuadas por nível. Barra do mês: **Plano ✔ 1.190 contas**.
- Todos os usuários importam o plano (importar é tarefa do Assistente, §4).
- Testado na tela com o plano real da Casa Criança (no banco de teste). 102 testes passando, inclusive com os 2 planos reais de AMOSTRAS (marcador `amostras`); ruff limpo. Banco real: versão 0003, sem dados.
- **Achado para o aprendizado:** o plano da Casa Criança tem 5 contas “ÁGUA E ESGOTO” em grupos diferentes (355 em 3.2.2.04, 10491, 10543, 10490, 10270, 10486 em 3.4/3.5/3.6/3.7 — provavelmente um grupo por programa/convênio). O lanctos.txt usa sempre a 355 → classificação deve seguir o histórico da empresa, não só a descrição.
- **Como testar:** abra a Casa Criança → aba **2 Plano de Contas** → envie `AMOSTRAS\PLANO DE CONTAS\contas crianca.csv` → veja 1.190 contas, os avisos e busque “agua”.

### 06/10/2026 — Etapa 1.3 concluída
- Tabela `empresa` (migração 0002, + extensão `unaccent`). **Só o código no Domínio é obrigatório** (critério da Fase 1).
- CNPJ e CPF validados pelos dígitos, **inclusive o CNPJ alfanumérico** (com letras) que a Receita emite desde julho/2026.
- Com CNPJ, o sistema consulta a BrasilAPI e preenche razão social, nome fantasia e **regime** (MEI/Simples/Presumido/Real/Terceiro setor) com o selo **🤖 automático**; o que o usuário digitou nunca é trocado; campo alterado à mão perde o selo. Sem internet: cadastra e avisa. Testado de verdade com a Casa Criança: “IMUNE DE IRPJ” → Terceiro setor.
- Página inicial = lista de empresas: busca instantânea sem acento (nome, CNPJ, código), “Só as minhas”, mês de trabalho (padrão: mês passado, lembrado entre telas) e situação do mês em pontinhos.
- Página da empresa: barra do mês (Plano → Aprendizado → Extrato → Revisão → Exportado; cada etapa futura liga a sua conferência em `app/servicos/progresso.py`), abas 1–6 (só Cadastro funciona; as outras dizem em que etapa chegam), dados públicos do CNPJ, modelo do complemento com exemplo ao vivo (padrão `FAVORECIDO - CNPJ - NATUREZA - DOCUMENTO`, igual ao lanctos.txt atual).
- Só o Supervisor cadastra/altera empresas; Assistente e Contador veem.
- 75 testes passando (nenhum acessa a internet); ruff limpo. Banco real: versão 0002, sem dados.
- **Como testar:** `INICIAR.bat` → entre como Supervisor → **+ Nova empresa** → digite só `230` e o CNPJ `06.101.084/0001-36` → veja razão social e regime chegarem sozinhos com 🤖 → altere o nome curto para “Casa Criança” e salve → volte à lista e busque “crianca”.

### 06/10/2026 — Etapa 1.2 concluída
- Banco com migrações (Alembic): tabelas `usuario` e `log`. INSTALAR e INICIAR criam/atualizam as tabelas sozinhos.
- **Primeiro acesso:** sem nenhum usuário, o sistema pede o cadastro do Supervisor na própria tela (não pergunta nada no INSTALAR).
- Login por usuário ou e-mail, senha guardada só como hash (argon2), sessão de 12 h. Trocar a senha encerra os logins abertos em outros computadores; usuário desativado sai na hora.
- Papéis Assistente / Contador / Supervisor. Só o Supervisor vê **Usuários** e **Log**; o sistema nunca fica sem um Supervisor ativo.
- **Log de auditoria automático:** toda inclusão/alteração/exclusão grava quem, quando, antes e depois (senha aparece como ***); entradas, saídas e senhas erradas também.
- **Identidade visual Zera** aplicada: logos oficiais (clara/escura), emblema na tela de entrada, preto e dourado, Cinzel, modo claro/escuro (botão ◐). Conferido no navegador em computador e celular.
- Servidor de teste (`scripts/servidor_teste.py`, porta 8001) para ver as telas sem tocar nos dados reais.
- 37 testes passando; ruff sem avisos. Banco real: versão 0001, nenhum usuário (o primeiro Supervisor é criado pelo usuário).
- **Como testar:** dois cliques no `INICIAR.bat` → aparece **Primeiro acesso** → cadastre-se como Supervisor → em **Usuários**, cadastre um Assistente → saia e entre como ele (não vê Usuários/Log) → volte como Supervisor e veja tudo no **Log**.

### 06/10/2026 — Etapa 1.1 concluída
- Projeto criado: FastAPI + Jinja2 + HTMX + Pico.css (arquivos locais), configuração pelo `.env`, PostgreSQL 16 no Docker (porta 127.0.0.1:5433, volume persistente).
- `INSTALAR.bat`: cria o ambiente Python, instala as bibliotecas, cria o `.env` com senhas aleatórias, cria `dados/` e liga o banco.
- `INICIAR.bat`: liga o Docker Desktop se precisar, espera o banco, sobe o sistema (~7 s) e abre o navegador; se já estiver aberto, só abre o navegador.
- Instalador do computador movido para `ferramentas\preparar_computador\` (`PREPARAR_COMPUTADOR.bat`).
- Copiados do Z:\ (só leitura) os lanctos.txt de 2026 (gabarito) e 2025 (aprendizado extra).
- 10 testes passando; ruff sem avisos.
- **Como testar:** dois cliques no `INICIAR.bat` → o navegador abre mostrando "Sistema no ar" e "Banco de dados conectado". Para desligar, feche a janela preta.
