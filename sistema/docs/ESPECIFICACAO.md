# PROMPT PARA O CLAUDE CODE — ZeraConcilia (versão final — automação máxima com IA)

> **Como usar:** salve este arquivo em `C:\1 - ZeraConcilia\` (substituindo as versões anteriores). Abra o PowerShell nessa pasta, digite `claude`, aperte **Shift+Tab** até aparecer *plan mode* e envie:
> `Leia o arquivo PROMPT_Claude_Code_ZeraConcilia.md inteiro e siga as instruções, começando pela FASE 0.`
> Se já existir um plano anterior, envie: `Descarte o plano anterior, leia a versão final do PROMPT_Claude_Code_ZeraConcilia.md e refaça o plano.`

---

## 1. O QUE CONSTRUIR

Um sistema web **simples e prático** para o escritório **Zera Contabilidade**, onde:

1. cada **empresa-cliente tem seu próprio cadastro**;
2. dentro de cada empresa o usuário carrega o **plano de contas**, o **Livro Diário ou Razão** (para o sistema **aprender** os fornecedores, clientes e padrões de lançamento daquela empresa) e os **extratos bancários**;
3. o sistema **se configura sozinho** a partir do plano de contas (descobre com IA qual é a conta de cada banco, da poupança, de rendimentos, de IR retido, de tarifas etc.);
4. o sistema **classifica sozinho** cada movimento do extrato na conta contábil correta (aprendizado + **IA**) e monta o histórico completo;
5. o usuário **só confere o que o sistema marcou como incerto** e **gera o `lanctos.txt` para importar no Domínio**.

**Por que construir:** hoje o trabalho é manual no Excel (filtrar fornecedor por fornecedor) e leva **mais de 1 hora por empresa por mês**. A importação de extrato nativa do Domínio já foi testada e **não atende** porque: (a) a regra só olha o histórico do banco ("Pagamento de Boleto") e não reconhece o fornecedor; (b) exige cadastrar regra por regra à mão; (c) o complemento do histórico sai pobre. **O ZeraConcilia existe para resolver exatamente esses três pontos.**

**Meta de sucesso:** **máximo de automação**. Já no 1º mês, **≥ 85% das linhas classificadas automaticamente e corretas**; a partir do 2º mês, **≥ 95%**, e **≈ 15 minutos por empresa por mês**. O sistema deve servir para **qualquer tipo de empresa** (Simples, Presumido, Real, MEI, terceiro setor).

---

## 2. PRINCÍPIOS (siga acima de tudo)

1. **Automação máxima.** O sistema **nunca pergunta ao usuário o que ele mesmo pode descobrir** (no plano de contas, no Diário/Razão, no extrato ou com IA). O usuário só intervém onde houver dúvida real (confiança baixa) e na exportação final.
2. **Simples e prático.** O usuário é contador, não programador. Poucas telas, poucos cliques. Se algo não ajuda a classificar e exportar mais rápido, fica para depois.
3. **Português do Brasil** em tudo. Mensagens de erro dizem **o que fazer** ("A conta 10595. não existe no plano — corrija na linha 7"), nunca códigos técnicos.
4. **Funciona de verdade.** Cada fase só termina com testes automáticos passando e com o fluxo testado nos arquivos reais de `amostras/`. Se um teste falhar, corrija a causa — nunca apague o teste.
5. **Não invente.** Os formatos de arquivo estão na seção 11. A IA também nunca inventa: só pode sugerir contas que existem no plano da empresa.
6. **Dinheiro sempre `Decimal`**, nunca `float`.
7. **Trabalhe em etapas pequenas (o usuário está no plano Claude Pro, que tem limite de uso).** Cada etapa termina com testes + **commit no Git** + atualização do arquivo **`PROGRESSO.md`** (o que foi feito, o que falta, próximo passo exato). Se a sessão for interrompida, a próxima começa lendo `CLAUDE.md` e `PROGRESSO.md` e continua de onde parou.
8. **Pronto para a nuvem desde o início:** nada de caminhos fixos de Windows no código; configurações (banco, pasta de arquivos, pasta de backup) em `.env`.

---

## 3. TELAS E FLUXO

```
[EMPRESAS] lista: nome, CNPJ, código Domínio, responsável, situação do mês   [+ Nova empresa]
     │
     ▼
[EMPRESA X] — barra de progresso do mês:  Plano ✔ → Aprendizado ✔ → Extrato ✔ → Revisão (12 pendentes) → Exportado
   Abas: 1 Cadastro · 2 Plano de Contas · 3 Aprendizado · 4 Extratos · 5 Revisão · 6 Exportar

[PAINEL DO SUPERVISOR] todas as empresas × mês: situação, quem exportou, quando, nº de linhas,
                        % classificado automaticamente, nº de correções manuais
```

### 3.1 Cadastro da empresa (preenchido automaticamente sempre que possível)
- Campos: razão social, nome curto, CNPJ, **código da empresa no Domínio** (campo 8 do TXT, ex.: 230), **responsável**, observações.
- **Preenchimento automático:** razão social e CNPJ vêm do cabeçalho do Diário/Razão (ex.: "Empresa: CASA CRIANCA ESPERANCA…", "C.N.P.J.: 06.101.084/0001-36"); opcionalmente completar pela consulta pública de CNPJ (BrasilAPI). O usuário só digita o **código no Domínio** (única informação que não está em nenhum arquivo).
- **Contas bancárias:** criadas **automaticamente** na primeira importação de extrato (banco, agência, conta e tipo lidos do arquivo) e **ligadas sozinhas à conta contábil** pela auto-configuração (3.2.1).
- **Conta individual por fornecedor/cliente:** detectada automaticamente pelo plano (ex.: grupo Fornecedores com muitas contas com nome de empresa); conta genérica também identificada pelo nome (ex.: "FORNECEDORES DIVERSOS").
- Modelo do **complemento do histórico** (padrão: `FAVORECIDO - NATUREZA - DOCUMENTO`).
- Tudo que foi preenchido automaticamente aparece com o selo **"🤖 automático"** e pode ser alterado.

### 3.2 Plano de Contas
- Importar o TXT exportado do Domínio (layout na seção 11.2), Excel ou CSV. Cada empresa tem o seu; opção "copiar de outra empresa".
- Tabela pesquisável: reduzido, classificação formatada, descrição, tipo (Sintética/Analítica).
- **Reimportar** atualiza sem perder o aprendizado (casa pelo código reduzido; avisa contas removidas). Após reimportar, **reclassificar automaticamente** as linhas pendentes (útil quando o usuário acabou de criar contas de fornecedores novos no Domínio).
- Avisos: classificação duplicada, descrição cortada, tipo inválido.

#### 3.2.1 Auto-configuração pelo plano de contas (com IA)
Logo após importar o plano (e de novo a cada extrato de banco novo), o sistema **descobre sozinho as "contas-chave"** da empresa, sem perguntar nada:

| Conta-chave | Como descobre (exemplo no plano da Casa Criança) |
|---|---|
| Conta de cada **banco/conta corrente** | casa banco + agência + nº da conta do extrato com a descrição das contas do grupo Disponível/Bancos (ex.: extrato BB ag. 2180-6 c/c 72637-0 → **8 – BCO BRASIL CC 72637-0**) |
| **Poupança / aplicação** | idem, procurando "POUPANÇA", "APLICAÇÃO", nome do banco, nº da conta (ex.: Poupança-Ouro BB → conta de poupança do BB no plano) |
| **Rendimentos** (juros, reajuste monetário) | grupo de receitas financeiras (ex.: "RENDIMENTOS DE APLICAÇÃO", "RECEITAS FINANCEIRAS") |
| **IR retido** sobre aplicação | "IRRF A COMPENSAR", "IMPOSTO DE RENDA RETIDO" |
| **Tarifas bancárias / IOF / juros pagos** | "DESPESAS BANCÁRIAS", "TARIFAS", "IOF", "JUROS PASSIVOS" |
| **Fornecedores / clientes genéricos** | "FORNECEDORES DIVERSOS", "CLIENTES DIVERSOS" |
| **Salários, FGTS, INSS, impostos a recolher** | descrições do passivo (ex.: 187 SALÁRIOS A PAGAR, 192 FGTS A RECOLHER) |

Como funciona:
1. Primeiro, **busca por regras** (palavras e números da conta) — rápido e sem custo.
2. O que não ficou certo vai para a **IA**, que recebe as contas analíticas do plano e os dados do banco e devolve, para cada conta-chave, `{conta_reduzida, confianca, justificativa}`.
3. Confiança alta → **aplicado automaticamente** (selo 🤖). Confiança baixa ou conta inexistente no plano → um único aviso: *"Não encontrei no plano uma conta para a poupança do BB — crie no Domínio e reimporte o plano, ou escolha uma conta"*.
4. A IA **só pode escolher contas que existem** no plano e que são **analíticas**; o sistema valida a resposta antes de gravar.

### 3.3 Aprendizado (o diferencial)
- Importar **Diário** ou **Razão** (xls/xlsx/csv/txt do Domínio). Vários períodos; sem duplicar.
- O sistema monta três listas **editáveis**:
  1. **Fornecedores/Favorecidos** — nome, CNPJ/CPF, conta, natureza mais comum, nº de vezes, total, último lançamento;
  2. **Clientes/Origens de recebimento** — mesma estrutura;
  3. **Palavras-chave** — ex.: "SALARIO MENSAL" → 187; "GUIA DE FGTS" → 192; "TARIFA" → despesas bancárias.
- Fornecedor lançado em contas diferentes → marcar **"ambíguo"** e deixar o usuário escolher.
- Resumo **"Despesas por conta"** do período importado, para conferência.
- O usuário pode criar, editar e desativar padrões.

### 3.4 Extratos
- **Arrastar e soltar** um ou vários arquivos de uma vez. O sistema **detecta sozinho** o banco, a agência/conta, o tipo (corrente/poupança) e o período, e liga à conta bancária da empresa (criando-a se for nova, com a conta contábil achada pela auto-configuração).
- **Regra dos bancos:**
  1. **OFX de qualquer banco** funciona desde o início (um leitor só);
  2. **PDF**: começar pelo **Banco do Brasil** (amostras disponíveis). Cada banco novo ganha seu leitor quando houver um PDF de exemplo em `amostras/extratos/NOME_DO_BANCO/` — estruture os leitores de PDF como **plug-ins** (um arquivo por banco) para facilitar;
  3. **Excel/CSV de qualquer banco**: o usuário indica as colunas uma vez; o sistema guarda o modelo por banco;
  4. **Banco sem leitor próprio de PDF (ou PDF em formato desconhecido) → leitor universal com IA:** o texto do PDF (ou a imagem da página, se for escaneado) é enviado à IA, que devolve as linhas em JSON `{data, descricao, documento, valor, sentido, saldo}`. O resultado só é aceito se **a conferência de saldo bater** (saldo inicial + movimentos = saldo final); se não bater, avisa e pede OFX/Excel. Assim **qualquer banco funciona desde o primeiro dia**; os leitores próprios (mais rápidos e sem custo) vão sendo criados para os bancos mais usados.
  5. Excel/CSV de layout desconhecido → a IA **identifica as colunas sozinha** (data, descrição, valor, débito/crédito, saldo); o usuário só confirma na primeira vez.
- Conferir **saldo inicial + entradas − saídas = saldo final**; se não bater, avisar a diferença.
- Não duplicar movimentos ao reimportar ou importar períodos sobrepostos.
- Guardar o **arquivo original** (ver seção 7) e, logo após importar, classificar e abrir a Revisão.

### 3.5 Revisão
- Grade tipo planilha: **Data | Descrição do banco | Valor | Débito | Crédito | Complemento | Confiança | Origem da sugestão**.
- Cores: 🟢 alta · 🟡 média · 🔴 pendente. Filtros: Todos / Pendentes / Amarelos / Por conta / **Só IA**. Busca.
- **Por padrão a tela abre filtrada no que precisa de atenção** (amarelos e vermelhos). Os verdes já vêm **aprovados automaticamente** (limiar configurável por empresa, padrão ≥ 90%); o usuário pode desfazer.
- Sugestões da IA mostram a **justificativa** ao passar o mouse (ex.: "LYTEX INSTITUICAO DE PAGAMENTO é intermediador de boletos; valor 910,00 igual ao PLANO ODONTOLÓGICO de meses anteriores").
- Campo de conta com **autocompletar** (digita "agua" ou "355" → "355 – ÁGUA E ESGOTO"); só contas **analíticas**.
- Seleção múltipla para aplicar a mesma conta de uma vez.
- Ao corrigir: o sistema **aprende** e pergunta *"Aplicar às outras X linhas parecidas?"*.
- Opção **"Ignorar"** linha.
- Lista **"Fornecedores a cadastrar no Domínio"** (nome + CNPJ, exportável em Excel) para empresas com conta individual: essas linhas ficam pendentes até a conta existir.

### 3.6 Exportar
- **Qualquer usuário** pode exportar.
- Escolher mês e contas bancárias.
- **Validações que bloqueiam** (mostrando a linha): pendentes (ou confirmação para deixá-las de fora), conta inexistente/sintética, data inválida ou fora do período, débito = crédito, valor ≤ 0, `;` no complemento.
- Gera **`lanctos.txt`** (formato da seção 11.1) + **resumo em Excel** por conta.
- Registra a exportação (quem, quando, quantas linhas); linhas exportadas ficam **travadas**. **Só o Supervisor reabre** um mês exportado (com registro no log).

---

## 4. USUÁRIOS E PERMISSÕES

| Papel | Pode |
|---|---|
| **Assistente** | importar, classificar, corrigir, exportar |
| **Contador** | o mesmo que o assistente |
| **Supervisor** | tudo + **painel de acompanhamento** de todas as empresas + cadastrar usuários e empresas + definir responsável + **reabrir mês exportado** |

- Login com e-mail/usuário e senha (hash seguro). Só a equipe do escritório usa (sem acesso de clientes nesta versão — deixar a estrutura preparada para um portal do cliente no futuro).
- **Log de auditoria** de toda alteração (quem, quando, antes/depois).

---

## 5. COMO CADA LANÇAMENTO É MONTADO

- **Saída do banco:** Débito = conta sugerida / Crédito = conta do banco.
- **Entrada no banco:** Débito = conta do banco / Crédito = conta sugerida.
- **Transferência entre contas da própria empresa** (ex.: conta corrente ↔ poupança): **um único lançamento** banco × banco. Se os dois extratos forem importados, parear (mesmo valor, sentido oposto, mesma data ou ±2 dias) e lançar uma vez só.
- **Rendimentos** (Juros, Reajuste Monetário) e **IR retido** em poupança/aplicação: padrões próprios configuráveis.
- **Complemento:** `FAVORECIDO - NATUREZA - DOCUMENTO` (ex.: `SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N`). Natureza vem do padrão aprendido; documento vem do extrato (ou `S/N`).

---

## 6. MOTOR DE APRENDIZADO E CLASSIFICAÇÃO (regras + aprendizado + IA)

Ideia central: **o que é repetitivo, o sistema resolve sozinho por regras e memória (rápido e grátis); o que é novo ou ambíguo, a IA resolve; o que nem a IA tem certeza, o usuário confere.** Cada resposta da IA aprovada vira padrão, então **a cada mês a IA é menos chamada** e o custo cai.

### 6.1 Aprender com Diário/Razão
1. Ler cada lançamento; **ignorar contas de banco/caixa** (contas-chave bancárias e grupo Disponível) — interessa a **contrapartida**.
2. Converter a **classificação** (ex.: `2.1.5.02.000002`) para o **código reduzido** pelo plano da empresa.
3. Extrair do histórico **CNPJ/CPF** (validar dígito), **nome do favorecido**, **natureza** e **valor** — primeiro por regras (texto antes do primeiro " - ", CNPJ por expressão regular); **históricos que as regras não conseguem separar vão para a IA em lotes**, que devolve `{favorecido, cnpj_cpf, natureza}`.
4. Normalizar: maiúsculas, sem acentos, sem espaços duplos, sem datas/números de documento.
5. Gravar padrões: fornecedor/cliente → conta; palavra-chave → conta; ocorrências; natureza mais usada; **valores recorrentes** (ex.: mesmo salário todo mês).
6. Ao final, a IA gera um **"perfil da empresa"** curto (atividade, principais fornecedores, despesas típicas, como os pagamentos são lançados — direto em despesa ou baixando passivo), guardado e reutilizado como contexto nas classificações.

### 6.2 Classificar cada movimento (ordem de prioridade)
1. Regras fixas de banco: transferência entre contas próprias, rendimentos, IR retido, tarifas, IOF (usando as contas-chave da auto-configuração).
2. **CNPJ/CPF igual** a padrão aprendido → alta.
3. **Nome parecido** (`rapidfuzz`, ex.: "EDP SAO PAULO DISTRIBUICAO DE" ≈ "EDP SÃO PAULO") → alta se ≥ 90, média se 75–89.
4. **Palavra-chave** → média/alta.
5. **Valor recorrente** → média.
6. **IA** para **tudo que sobrou** (pendentes e médias) — **automático, sem botão**:
   - envia em **lotes** (ex.: 30–50 linhas por chamada) com: plano de contas **analítico** da empresa, perfil da empresa, padrões aprendidos mais relevantes e exemplos de lançamentos parecidos já aprovados;
   - resposta **obrigatoriamente estruturada** (tool use/JSON): `{id_linha, conta_debito, conta_credito, favorecido, natureza, complemento, confianca, justificativa}`;
   - o sistema **valida** (conta existe, é analítica, débito ≠ crédito, um dos lados é o banco do extrato); resposta inválida → linha pendente;
   - confiança da IA ≥ 90 → verde; 70–89 → amarela; < 70 → vermelha.
7. Fornecedor identificado mas **sem conta** (empresa com conta individual) → pendente + lista "Fornecedores a cadastrar no Domínio" (a IA já sugere o nome da conta a criar e o grupo onde criar). Sem conta individual → conta genérica.

Cada sugestão mostra **de onde veio** ("Fornecedor SABESP – 6 lançamentos no Diário" ou "🤖 IA: …justificativa").

### 6.3 Aprendizado contínuo
Toda aprovação/correção (inclusive das sugestões da IA) atualiza os padrões da empresa. Na próxima vez, a mesma linha é resolvida no passo 2–5, sem IA.

### 6.4 Configuração e controle da IA
- **API da Anthropic (Claude)** pelo SDK oficial `anthropic` (Python). Chave em `.env` (`ANTHROPIC_API_KEY`) — **é diferente da assinatura Claude Pro**: precisa de conta em console.anthropic.com com créditos.
- **Modelos configuráveis no `.env`**: um modelo rápido e barato (família Haiku) para leitura de históricos e classificação em lote; um modelo mais forte (família Sonnet) para auto-configuração, leitor universal de PDF e casos difíceis. Consulte a documentação atual da Anthropic para os nomes de modelo vigentes.
- Usar **prompt caching** para o plano de contas e o perfil da empresa (são reenviados a cada lote) — reduz custo.
- **Limite de gasto mensal** configurável (geral e por empresa); ao atingir, a IA para e as linhas ficam pendentes, com aviso.
- **Painel de uso da IA**: chamadas, linhas resolvidas, custo estimado por empresa/mês.
- Liga/desliga por empresa (padrão: **ligado**).
- Toda chamada registrada (entrada resumida, resposta, modelo, custo) para auditoria.
- Se a API estiver fora do ar ou sem internet, o sistema **continua funcionando** só com regras e aprendizado; a IA roda depois (botão "Reprocessar com IA").
- Dados enviados: apenas o necessário (descrição, valor, data, plano de contas, padrões). Nunca enviar senhas ou dados de login.

### 6.5 Exportação automática (opcional por empresa)
Se **todas** as linhas do mês estiverem verdes e a conferência de saldo bater, o sistema pode **gerar o `lanctos.txt` automaticamente** e avisar no painel ("Casa Criança — setembro pronto para importar"). Desligado por padrão; o Supervisor liga por empresa quando confiar.

---

## 7. INFRAESTRUTURA

### 7.1 Agora (construção e uso inicial) — no computador do escritório
- **Banco de dados: PostgreSQL 16 no Docker** (o Docker Desktop já está instalado e funcionando). `docker-compose.yml` só para o banco, com volume persistente.
- **Aplicação:** Python 3.12 + **FastAPI** + Uvicorn, rodando num ambiente virtual (`.venv`).
- `INSTALAR.bat` → cria `.venv`, instala dependências, sobe o banco e roda as migrações.
- `INICIAR.bat` → abre o Docker Desktop se estiver fechado, espera o banco, inicia o sistema e **abre o navegador** em `http://localhost:8000`.
- **Fases 1–3:** acesso só local (só a supervisora usa).
- **Depois da Fase 3:** opção de liberar para a **rede do escritório** (ouvir em `0.0.0.0`, regra no Firewall do Windows) com instruções simples em `docs/acesso_pela_rede.md`.

### 7.2 Backup
- Backup automático **diário** (e ao iniciar) com `pg_dump` + pasta de arquivos originais, gravado na pasta do **Google Drive** sincronizada no computador (caminho configurável no `.env`, ex.: `G:\Meu Drive\Backups ZeraConcilia`). Manter as **últimas 30 cópias**.
- `RESTAURAR.bat` + instrução passo a passo de restauração.

### 7.3 Arquivos originais
- Extratos, Diários/Razões e planos enviados ficam guardados (pasta configurável), ligados à importação que geraram, por **5 anos**; depois, exclusão automática (com registro no log). Acesso só para usuários logados.

### 7.4 Depois (nuvem — Fase 4)
- Migrar para **Supabase** (PostgreSQL, região São Paulo) + **Render** (aplicação), ~US$ 32/mês. Como o banco já é PostgreSQL, migrar = trocar `DATABASE_URL` + mover arquivos para o armazenamento do Supabase. Escrever o código de armazenamento de arquivos com uma interface (`ArmazenamentoLocal` agora, `ArmazenamentoSupabase` depois).

### 7.5 Tecnologias
| Parte | Escolha |
|---|---|
| Telas | **Jinja2 + HTMX + Tabulator** (grade tipo planilha) + CSS simples (Pico.css). JS/CSS salvos localmente. Sem React, sem build |
| Banco | PostgreSQL + SQLAlchemy 2 + Alembic |
| Leitura | `ofxtools` (OFX), `pdfplumber` (PDF), `openpyxl` (xlsx), **`python-calamine`** (xls do Domínio — o `xlrd` não lê; o calamine lê, já testado), `pandas` (CSV) |
| Similaridade | `rapidfuzz` |
| IA | SDK oficial **`anthropic`** (API do Claude), saída estruturada via *tool use*, *prompt caching*; módulo `app/ia/` isolado com um **cliente falso (mock)** para testes |
| Testes | `pytest`; testes de tela com o **Playwright MCP** já instalado no Claude Code |
| Qualidade | `ruff` |

---

## 8. TABELAS (mínimo)

`usuario` (papel), `empresa` (responsável, código Domínio, usa_conta_individual, conta_generica_fornecedor, conta_generica_cliente, modelo_complemento), `conta_bancaria`, `conta_contabil` (por empresa), `arquivo_original` (caminho, hash, tipo, data, expira_em), `importacao`, `lancamento_historico` (Diário/Razão), `padrao` (FORNECEDOR/CLIENTE/PALAVRA, texto normalizado, CNPJ, conta, natureza, ocorrências, ambíguo, ativo), `modelo_planilha_banco`, `conta_chave` (empresa, tipo — BANCO/POUPANÇA/RENDIMENTO/IR_RETIDO/TARIFA/IOF/FORNECEDOR_GENERICO… —, conta, origem REGRA/IA/USUÁRIO, confiança), `perfil_empresa` (texto gerado pela IA), `chamada_ia` (empresa, finalidade, modelo, tokens, custo, data), `movimento_extrato` (hash anti-duplicidade), `sugestao` (débito, crédito, complemento, confiança, origem, status PENDENTE/APROVADO/IGNORADO/EXPORTADO), `exportacao`, `fornecedor_a_cadastrar`, `log`.

---

## 9. FASES (uma por vez, em etapas pequenas com commit)

| Fase | Entrega | Pronto quando |
|---|---|---|
| **0 – Plano** | Lê `amostras/`, faz as perguntas da seção 12, apresenta o plano dividido em etapas pequenas, cria `CLAUDE.md` e `PROGRESSO.md` | Eu aprovo |
| **1 – Base, Empresas, Plano, Aprendizado e Auto-configuração** | Docker/PostgreSQL, INSTALAR/INICIAR.bat, login e papéis, cadastro de empresas (preenchimento automático), importação do plano TXT, **módulo de IA** (cliente, limites, log de custo), **auto-configuração das contas-chave** (regras + IA), detecção de conta individual, importação do Diário.xls com extração por regras + IA, perfil da empresa, listas de fornecedores/clientes/palavras-chave, backup no Google Drive | Crio a Casa Criança informando só o código 230, importo plano e Diário e o sistema **sozinho** mostra as contas-chave (banco 8 etc.) e os fornecedores com as contas corretas |
| **2 – Extratos e Revisão** | Arrastar e soltar com detecção automática, leitor OFX, leitor PDF BB (CC e poupança), **leitor universal de PDF com IA**, Excel/CSV com colunas identificadas pela IA, conferência de saldo, anti-duplicidade, classificação regras + **IA automática em lote**, transferências, aprovação automática dos verdes, tela de Revisão, lista de fornecedores a cadastrar | Importo os 2 PDFs do BB e **≥ 85%** das linhas vêm verdes e corretas; transferências saem uma vez só |
| **3 – Exportação e Painel** ✅ *sistema utilizável* | `lanctos.txt` + validações + resumo Excel, travamento e reabertura pelo Supervisor, painel do supervisor, log, guarda de arquivos 5 anos, acesso pela rede | O TXT tem exatamente o formato do modelo e **importo no Domínio com sucesso** |
| **4 – Extras** | Leitores próprios de PDF dos bancos mais usados (reduz custo de IA); exportação automática por empresa; relação de pagamentos (aba DADOS) cruzada com extrato; migração para a nuvem | Um item por vez, quando eu pedir |

Ao fim de cada fase: todos os testes passando, commit, `CLAUDE.md` e `PROGRESSO.md` atualizados, e explicação **em linguagem simples** de como testar.

---

## 10. QUALIDADE

- Começar em **modo de planejamento**; não programar antes da aprovação.
- Testes para: plano TXT, Diário.xls, extração de CNPJ/nome/natureza, PDFs do BB, OFX, pareamento de transferências, classificação, detecção de conta individual, **auto-configuração** (ex.: extrato BB 72637-0 → conta 8), validações, geração do TXT, permissões (só Supervisor reabre mês).
- **IA nos testes:** os testes automáticos usam o **cliente falso (mock)** com respostas gravadas — rodam sem internet e sem custo. Além disso, um comando separado `pytest -m ia_real` roda um teste real com a API nas amostras e mostra a **taxa de acerto** contra o TXT modelo (as 195 linhas classificadas pelo escritório servem de gabarito).
- **Validação da IA:** testar que respostas com conta inexistente, conta sintética, JSON inválido ou débito = crédito são **rejeitadas** e viram pendentes.
- **Teste "arquivo de ouro":** gerar o TXT a partir dos lançamentos do modelo (com os 3 erros conhecidos corrigidos) e comparar com o formato do modelo, linha a linha.
- `amostras/`, `.env`, dados e backups **fora do Git**; testes usam cópias **anonimizadas**.
- Medir e mostrar no painel o **% classificado automaticamente** por empresa/mês (é a meta do projeto).

---

## 11. FATOS JÁ VERIFICADOS NAS AMOSTRAS (especificação)

### 11.1 `lanctos.txt` aceito pelo Domínio
Referência: `amostras/planilha exportação/modelo exemplar da exportacao.txt` (gerado pela macro `Gerar()` da `EXPORTAÇÃO DOMINIO.xlsm`, **já aceito pelo Domínio**).

| # | Campo | Exemplo | Regra |
|---|---|---|---|
| 1 | Data | `05/01/2026` | dd/mm/aaaa |
| 2 | Conta Débito | `492` | código reduzido, sem zeros à esquerda |
| 3 | Conta Crédito | `8` | código reduzido |
| 4 | Valor | `150,17` · `120` · `346,5` | vírgula decimal, sem milhar (igual ao modelo) |
| 5 | Cód. Histórico | *(vazio)* | opcional |
| 6 | Complemento | `SABESP - 43.776.517/0001-80 - CONTA DE AGUA - S/N` | sem `;` |
| 7 | Inicia Lote | `1` | `1` em toda linha |
| 8 | Código Matriz/Filial | `230` | código da empresa no Domínio |
| 9 | C. Custo Débito | *(vazio)* | |
| 10 | C. Custo Crédito | *(vazio)* | |

Separador `;`, 10 campos (linha termina em `;;`), sem cabeçalho, **CRLF**, **Windows-1252**. O modelo tem **3 erros** que o sistema deve bloquear: `28/01//2026`, `28/01//2027` e conta `10595.`.

### 11.2 Plano de contas — `amostras/plano_de_contas/contas crianca.txt`
Largura fixa, 78 colunas, Windows-1252, CRLF: col. 1–7 **reduzido** (`0000008` → 8); col. 8–27 **classificação** sem pontos (`11102000001` → `1.1.1.02.000001`, máscara 1.1.1.2.6); col. 28–67 **descrição**; col. 68+ **tipo** S/A. Ignorar última linha (só `9`). Descrição longa pode invadir o tipo → deduzir pela hierarquia. Reduzidos 10594 e 10595 com mesma classificação → aceitar e avisar.

### 11.3 Diário — `amostras/Diário.xls`
Ler com `python-calamine` (testado: aba "Diário", 417 linhas). **Não** usar o `Diário.pdf` (texto sobreposto). Cabeçalho da empresa nas primeiras linhas; títulos `Data | Classificação | Descrição | Histórico | Débito | Crédito`; ignorar "TOTAL DO DIA" e vazias; converter classificação → reduzido. Localizar colunas pelo título (o Razão terá formato parecido; adaptar quando houver amostra).

### 11.4 Extratos BB (PDF com texto)
- **Conta corrente:** `Dt. balancete | Ag. origem | Lote | Histórico | Documento | Valor R$ | Saldo`; valor com `C`/`D`; linha "Saldo Anterior"; **descrição em 2 linhas** (a 2ª traz o favorecido: "Pagamento de Boleto" + "SABESP") → juntar.
- **Poupança-Ouro:** `Dt. lançamento | Dt. base | Dia | Histórico | Documento | Informações | Valor | Saldo`; textos quebrados; Juros e Reajuste Monetário (créditos), Imposto De Renda (débito), Transferência Para Conta / Transferência de Crédito.
- CC e poupança com mesma agência/conta (2180-6 / 72637-0).

### 11.5 Planilha atual `EXPORTAÇÃO DOMINIO.xlsm` (substituída pelo sistema)
Abas **DADOS** (Data, Nº doc, Credor, Natureza, Valor), **DESCRIÇÃO** (`CREDOR - NATUREZA - DOCUMENTO`), **EXPORTAÇÃO** (campos do TXT; conta digitada à mão), **MAPEAMENTO** (palavra-chave → conta, quase vazio). As 195 linhas do TXT modelo também servem de **aprendizado inicial**.

### 11.6 Empresa-piloto
**Casa Criança Esperança Nossa Senhora do Monte Berico** — CNPJ 06.101.084/0001-36 — código **230** — associação/creche (terceiro setor), repasse municipal, prestação de contas, **conta individual por fornecedor** (ex.: 2.1.3.01.000190 ZERA ASSESSORIA). Conta 8 = BCO BRASIL CC 72637-0.

---

## 12. PERGUNTAS PARA A FASE 0

**Não pergunte o que o sistema deve descobrir sozinho** (conta da poupança, do banco, de rendimentos, de IR retido etc. — isso é trabalho da auto-configuração, seção 3.2.1). Pergunte apenas:

1. Caminho exato da pasta do **Google Drive** para os backups.
2. Se a **chave da API da Anthropic** já foi criada (se não, explique em passos simples como criar em console.anthropic.com, colocar créditos e definir um limite de gasto).
3. Limite de gasto mensal com IA desejado (sugestão: começar com US$ 20/mês).
4. Dúvidas que **realmente** não possam ser resolvidas pelos arquivos de `amostras/`.

---

**Comece agora pela FASE 0: leia `amostras/`, faça as perguntas da seção 12 e apresente o plano em etapas pequenas. Não escreva código antes da minha aprovação.**
