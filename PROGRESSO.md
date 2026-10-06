# PROGRESSO — ZERA CONTÁBIL MAX

Atualizado em: **06/10/2026**

## Próximo passo exato
**Etapa 1.2 — Banco, login e papéis:** SQLAlchemy 2 + Alembic; tabelas `usuario` e `log`; login com senha (hash seguro); papéis Assistente / Contador / Supervisor; criação do primeiro Supervisor durante o INSTALAR; sessão por cookie (`CHAVE_SESSAO`); log de auditoria (quem, quando, antes/depois); INSTALAR e INICIAR passam a aplicar as migrações; testes de banco num banco separado `*_teste`.

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
- [ ] 1.2 Banco de dados, login, papéis e log de auditoria
- [ ] 1.3 Cadastro de empresas e barra de progresso do mês
- [ ] 1.4 Importação do plano de contas (TXT/Excel/CSV), avisos, reimportação, copiar de outra empresa
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

### 06/10/2026 — Etapa 1.1 concluída
- Projeto criado: FastAPI + Jinja2 + HTMX + Pico.css (arquivos locais), configuração pelo `.env`, PostgreSQL 16 no Docker (porta 127.0.0.1:5433, volume persistente).
- `INSTALAR.bat`: cria o ambiente Python, instala as bibliotecas, cria o `.env` com senhas aleatórias, cria `dados/` e liga o banco.
- `INICIAR.bat`: liga o Docker Desktop se precisar, espera o banco, sobe o sistema (~7 s) e abre o navegador; se já estiver aberto, só abre o navegador.
- Instalador do computador movido para `ferramentas\preparar_computador\` (`PREPARAR_COMPUTADOR.bat`).
- Copiados do Z:\ (só leitura) os lanctos.txt de 2026 (gabarito) e 2025 (aprendizado extra).
- 10 testes passando; ruff sem avisos.
- **Como testar:** dois cliques no `INICIAR.bat` → o navegador abre mostrando "Sistema no ar" e "Banco de dados conectado". Para desligar, feche a janela preta.
