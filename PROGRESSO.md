# PROGRESSO — ZERA CONTÁBIL MAX

Atualizado em: **06/10/2026**

## Próximo passo exato
**Etapa 1.5 — Módulo de IA** (ler antes a skill `claude-api`): pacote `app/ia/` isolado com cliente real (SDK `anthropic`, saída estruturada por *tool use*, *prompt caching* do plano/perfil) e **cliente falso** com respostas gravadas para os testes; modelos no `.env` (rápido = Haiku 4.5 para lotes; forte = Sonnet 5.5 para auto-configuração/PDF); `ANTHROPIC_API_KEY` no `.env` (vazio = IA desligada, sistema segue só com regras); tabela `chamada_ia` (empresa, finalidade, modelo, tokens, custo estimado, resumo da entrada/resposta) — migração `0004`; limite de gasto mensal geral e por empresa (ao atingir: para e avisa); liga/desliga por empresa (padrão ligado); painel simples de uso (Supervisor); `pytest -m ia_real` separado. **Pendente com o usuário:** chave da API e limite mensal (sugestão US$ 20) — dá para construir e testar tudo com o cliente falso antes.

## Pendências com o usuário
| # | Pergunta | Precisa até |
|---|---|---|
| 1 | Destino do backup — o Google Drive para computador **não está instalado**; o Z:\ está disponível. Recomendado: os dois. | Etapa 1.9 |
| 2 | Chave da API Anthropic já criada? (o cliente falso dos testes funciona sem ela) | Etapa 1.5 |
| 3 | Limite mensal de gasto com IA (sugestão: US$ 20) | Etapa 1.5 |
| 4 | **Diário.xls** da Casa Criança (jan–ago/2026) em `AMOSTRAS\historicos` | Etapa 1.7 |
| 5 | Como a poupança BB 72637-0 é lançada hoje (conta própria ou tudo na conta 8)? Talvez o Diário responda. | Etapa 1.6 |

## Plano (Fase 0 aprovada em 06/10/2026)

### Fase 1 — Base e Aprendizado
- [x] 1.1 Estrutura do projeto, PostgreSQL no Docker, INSTALAR.bat / INICIAR.bat, CLAUDE.md, PROGRESSO.md
- [x] 1.2 Banco de dados, login, papéis e log de auditoria (+ identidade visual Zera)
- [x] 1.3 Cadastro de empresas e barra de progresso do mês
- [x] 1.4 Importação do plano de contas (TXT/Excel/CSV), avisos, reimportação, copiar de outra empresa
- [ ] 1.5 Módulo de IA: cliente real + falso, limites de gasto, registro de custo
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
