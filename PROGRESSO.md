# PROGRESSO — ZERA CONTÁBIL MAX

Atualizado em: **07/10/2026**

## Próximo passo exato
**Etapa 2.6 — Motor de classificação** (§6.2 passos 1–5 e 7; a IA para o que sobrar é a 2.7).
- Tabela `sugestao` (migração 0011; §8): movimento_extrato (1:1), conta débito, conta crédito, complemento (montado por `empresa.modelo_complemento` com `montar_complemento`), confiança (0–100), origem (REGRA, CNPJ, NOME, PALAVRA, VALOR, IA, USUARIO), justificativa (“Fornecedor SABESP – 6 lançamentos no histórico”), padrão usado, status PENDENTE/APROVADO/IGNORADO/EXPORTADO. Lado do banco = conta contábil da conta bancária (`conta.conta_chave.conta`); SAIDA → débito = contrapartida, crédito = banco; ENTRADA → o contrário.
- Ordem (`app/servicos/classificacao.py`), parar no 1º que resolver:
  1. **Regras de banco** com as contas-chave: transferência entre contas próprias (CC ↔ poupança: mesmo dia e valor, sentidos opostos, nas contas bancárias da empresa — códigos BB 875/141 e 475/601; as duas pontas na mesma conta contábil quando a poupança não tem conta própria → avisar), rendimentos (Juros, Reajuste Monetário, RENDIMENTO) → conta-chave RENDIMENTO, IR (Imposto De Renda) → IR_RETIDO, TARIFA, IOF.
  2. **CNPJ/CPF** escrito no movimento = de um padrão → alta (95).
  3. **Nome parecido** com `rapidfuzz` (acrescentar ao requirements) entre o complemento do banco (“ZERA ASSESSORIA EMPRESARIAL E”, cortado) e o nome do padrão: ≥ 90 alta, 75–89 média (comparar normalizado, `token_set_ratio`/`partial_ratio` por causa do corte).
  4. **Palavra-chave** (padrões PALAVRA) → média/alta; 5. **valor recorrente** do padrão → média.
  7. Fornecedor achado mas sem conta (empresa com conta individual) → PENDENTE + “Fornecedores a cadastrar no Domínio”.
- Roda sozinho depois de importar o extrato e por um botão “Classificar de novo”; não mexe em sugestão APROVADA/IGNORADA/USUARIO. Verdes (≥ limiar, padrão 90) já vêm APROVADOS (§3.5).
- Aba Extratos (ou início da aba Revisão): coluna Débito/Crédito/Complemento/Confiança/Origem nos movimentos. Tela de revisão completa é a 2.8.
- **Medir com os PDFs reais** (Casa Criança: lanctos 2025/2026 aprendidos + extratos de agosto): quantos ficam verdes/amarelos/pendentes — a meta da 2.8 é ≥ 85% certos.

## Pendências com o usuário
| # | Pergunta | Precisa até |
|---|---|---|
| 1 | ~~Destino do backup~~ — usuário pediu **Google Drive** (07/10). O Google Drive para computador **não está instalado**: o usuário precisa instalar e entrar na conta do escritório; o sistema acha `Meu Drive\Backups ZERA CONTABIL MAX` sozinho. Até lá, backup só em `dados\backups` (a tela avisa). | — |
| 2 | ~~Chave da API~~ — colada no `.env` em 07/10 (lida do arquivo do usuário no Z:\, sem passar pelo chat); `pytest -m ia_real` ok nos dois modelos. Nunca pedir nem mostrar a chave. | — |
| 3 | Limite mensal de IA: adotado o padrão **US$ 20** (`IA_LIMITE_MENSAL_USD`) até o usuário dizer outro valor | — |
| 4 | ~~Diário.xls~~ — chegou em 07/10 (jan–jun/2026), copiado para `AMOSTRAS\historicos` | — |
| 5 | Como a poupança BB 72637-0 é lançada hoje (conta própria ou tudo na conta 8)? O Diário enviado não responde (só tem o Passivo); os rendimentos vão a crédito de 2.2.2.01.000006 RENDIMENTO A APLICAR. O extrato da poupança já é lido; falta a conta contábil (o sistema avisa e deixa escolher na aba Plano → contas-chave). | Etapa 2.6 |
| 7 | ~~OFX real~~ — o usuário indicou os OFX da APAE (228) no Z:\ em 07/10; 36 copiados para `AMOSTRAS\EXTRATOS\OFX APAE 2025-12`. | — |
| 6 | **Diário completo** (todas as contas) da Casa Criança — o enviado em 07/10 foi impresso só com o Passivo. Com ele o sistema aprende também as contas de banco, despesas e receitas. Não bloqueia. | quando puder |

## Plano (Fase 0 aprovada em 06/10/2026)

### Fase 1 — Base e Aprendizado
- [x] 1.1 Estrutura do projeto, PostgreSQL no Docker, INSTALAR.bat / INICIAR.bat, CLAUDE.md, PROGRESSO.md
- [x] 1.2 Banco de dados, login, papéis e log de auditoria (+ identidade visual Zera)
- [x] 1.3 Cadastro de empresas e barra de progresso do mês
- [x] 1.4 Importação do plano de contas (TXT/Excel/CSV), avisos, reimportação, copiar de outra empresa
- [x] 1.5 Módulo de IA: cliente real + falso, limites de gasto, registro de custo
- [x] 1.6 Auto-configuração das contas-chave + detecção de conta individual por fornecedor
- [x] 1.7a Importação do Diário (Excel do Domínio): partidas, Diário filtrado, classificação → conta, cadastro preenchido sozinho, sem contar em dobro com o lanctos.txt
- [x] 1.7b IA no histórico: o que as regras não separam (favorecido/natureza) e lançamentos com um lado só; contas-chave pela evidência do histórico
- [x] 1.8 Listas de fornecedores, clientes e palavras-chave; perfil da empresa; aprendizado inicial com os lanctos.txt de 2025 e 2026
- [x] 1.9 Backup automático (computador + Google Drive) + RESTAURAR.bat

### Fase 2 — Extratos e Revisão
- [x] 2.1 Arrastar e soltar, detecção automática, anti-duplicidade, guarda do original
- [x] 2.2 Leitor OFX
- [x] 2.3 Leitor PDF BB conta corrente
- [x] 2.4 Leitor PDF BB poupança
- [x] 2.5a Leitor universal com IA (PDF de banco sem leitor próprio, só entra se o saldo conferir)
- [x] 2.5b Excel/CSV com colunas identificadas pelos títulos ou pela IA (confirmação na 1ª vez)
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

### 07/10/2026 — Etapa 2.5b concluída (extrato em Excel/CSV)
- `app/leitores/planilha.py`: lê xlsx/xls (calamine, a aba com mais datas) e CSV (`;`, `,` ou tab); valores do jeito dos bancos (“1.234,56”, “-1.234,56”, “1.234,56 D”, “(10,00)”, número do Excel); datas dd/mm/aaaa, dd/mm/aa ou do Excel; títulos comuns (Data, Histórico/Lançamento, Documento, Valor, Débito, Crédito, C/D, Saldo); linhas “SALDO ANTERIOR/DO DIA” viram saldo; sem saldo anterior, o inicial sai da coluna Saldo da 1ª linha.
- `app/servicos/planilha_extrato.py`: colunas pelo **modelo já confirmado** (assinatura dos títulos), senão pelos títulos, senão pela **IA** (modelo rápido, 15 primeiras linhas). **1ª vez de cada layout → tela de confirmação** (`/empresas/{id}/extratos/planilha/{arquivo}`): primeiras linhas, colunas sugeridas (pode trocar), conta bancária (lista da empresa ou nova; banco/agência/conta escritos no alto da planilha já vêm preenchidos). O arquivo fica guardado esperando (lista “Planilhas esperando a sua confirmação” na aba). Modelo vale para todas as empresas (`modelo_planilha_banco`, migração 0010); a conta bancária guarda o layout (`assinatura_planilha`) → a próxima planilha igual entra direto.
- Testes (16): 263 passando. Tela conferida no servidor de teste (Playwright): confirmação → “Itaú · 2 movimentos — saldo confere”.

### 07/10/2026 — Etapa 2.5a concluída (PDF de qualquer banco pela IA)
- `app/leitores/universal_ia.py`: quando nenhum leitor próprio reconhece um PDF com texto (`NaoReconhecido`), o serviço manda **uma página por chamada** ao modelo forte (resposta pequena e rápida), junta as páginas (cabeçalho da 1ª que mostra, saldo inicial da 1ª, final da última) e confere cada linha (data no período, valor > 0, sentido). `exige_conferencia`: **só entra se o saldo conferir** — senão nada é gravado e a tela pede o OFX ou o Excel. IA desligada → mensagem pedindo o OFX.
- **Real:** o PDF da conta corrente do BB lido pela IA como se fosse banco desconhecido deu exatamente o mesmo do leitor próprio (49 movimentos, entradas = saídas = 149.568,52, ag. 2180-6, conta 72637-0, favorecidos separados) — **US$ 0,07**, 3 páginas, até 22 s cada.
- Testes (5 + 1 real).

### 07/10/2026 — OFX reais do BB (APAE, dez/2025)
- 36 OFX reais testados: 32 lidos, 4 “vazios do banco” (só cabeçalho) → mensagem clara “veio vazio do banco, baixe de novo”.
- Ajustes pelo jeito do BB: histórico e favorecido separados do MEMO (“TRANSFERÊNCIA RECEBIDA - 04/12 12:19 APAE…”), como no PDF; **agência pelo nome do arquivo** (`Extrato68829…` → 6882-9; o OFX do BB não traz BRANCHID); período começa no 1º dia do mês dos movimentos (o BB começa no dia do saldo anterior); saldo do OFX só vale se for do fim do período (o BB manda o saldo do dia do download → aviso).
- Teste `amostras` com os 36 arquivos; 242 testes passando.

### 07/10/2026 — Etapa 2.2 concluída (OFX)
- `app/leitores/ofx.py`: leitor próprio e tolerante (SGML do OFX 1.x sem fechar tags, XML do 2.x, Windows-1252, vírgula decimal); banco pelo BANKID (001, 0341...), agência (pode faltar), conta, tipo (CHECKING/SAVINGS/MONEYMRKT), período, movimentos (sentido pelo sinal; MEMO/NAME; CHECKNUM/REFNUM) e saldo final (LEDGERBAL). Recusa cartão de crédito e arquivo com várias contas, com mensagem do que fazer.
- **Mesma conta, escritas diferentes:** `mesma_conta` (“72637-0” = “0000726370”; agência só desempata se os dois lados têm); o OFX sem agência é completado pelo PDF.
- **PDF e OFX do mesmo mês não duplicam:** o hash do movimento passou a ser conta + dia + sentido + valor + nº da vez no dia (sem o texto, que cada formato escreve de um jeito).
- **Saldo inicial do OFX** = saldo final do extrato da véspera da mesma conta → conferência funciona mês a mês; sem o mês anterior, aviso.
- Testes (10, com OFX fictícios montados no teste). Sem OFX real nas amostras (pendência 7).


### 07/10/2026 — Etapa 2.4 concluída (PDF da poupança do BB)
- `app/leitores/bb_poupanca.py`: junta as até 3 linhas de cada lançamento pela proximidade com a linha da data (histórico e informações quebrados; valor numa linha e C/D em outra); colunas pelo cabeçalho; ignora o calendário de rendimentos do fim.
- Saldo: o anterior sai cortado (“227.4”) → calculado pelo saldo final do cabeçalho (só aceito se bater com o “Saldo total” do fim, também cortado; senão aviso “saldo de outra data”) e **conferido pelos dígitos visíveis** (`saldo_inicial_visivel`). Tela: “a impressão do PDF cortou parte do saldo”.
- **Real (ago/2026):** 28 movimentos, saldo 227.494,23 → 239.233,33 **confere**; conta bancária POUPANÇA 72637-0 criada; sem conta contábil no plano → aviso (pendência 5). As transferências batem com a CC: poupança 141 = CC 875 e poupança 601 = CC 475 (base do pareamento da 2.6).
- Testes (4 + 1 real): extratos 21 testes.


### 07/10/2026 — Etapas 2.1 + 2.3 concluídas (receber extratos + PDF do BB conta corrente)
- Tabelas (migração 0009): `conta_bancaria` (criada sozinha pelo 1º extrato; ligada à conta-chave bancária — reusa a que já existe, ex.: “BB conta 72637-0” → 8 achada pelo histórico; senão `ligar_conta_bancaria`), `extrato` (período, saldos, entradas/saídas, conferência) e `movimento_extrato` (histórico do banco + 2ª linha com o favorecido, documento, código, **hash anti-duplicidade**).
- `app/leitores/`: leitores como plug-ins (registro `LEITORES`, detecção pelo conteúdo); `bb_conta_corrente.py` lê **pela posição das palavras** (colunas pelo cabeçalho da 1ª página; valor/C-D que caem para a linha de baixo; saldo cortado “0,”). `pdfplumber` no requirements.
- `app/servicos/extratos.py`: importa, recusa conta de outra empresa, confere o saldo (cortado → confere até R$ 1,00, com sinal desconhecido), avisa diferença e conta contábil não encontrada; reimportar/período sobreposto não duplica (dois movimentos iguais no mesmo dia contam pela ordem).
- Aba **4 Extratos**: zona de **arrastar e soltar** (vários arquivos; envia ao soltar), contas bancárias com a conta contábil, extratos do mês com a conferência, movimentos do mês. Um arquivo ruim não atrapalha os outros. Barra do mês: **Extrato ✔ N movimentos**.
- **Real (PDF ago/2026 da Casa Criança):** 49 movimentos, entradas = saídas = **149.568,52**, saldo 0 → 0 **confere**, conta 72637-0 → **conta 8** pela regra. Tela conferida no servidor de teste (Playwright).
- Testes (17): 225 passando, ruff ok.


### 07/10/2026 — Etapa 1.7b concluída (IA no histórico) — Fase 1 completa
- `app/servicos/historico_ia.py`: a IA (modelo rápido, lotes de 40, até 10 lotes por vez) revisa o que as regras não resolveram — lançamento com **um lado só** fora do banco (foi pagamento/recebimento pelo banco ou lançamento interno?) e pagamento/recebimento com histórico **sem “ - ”** (separa favorecido, CNPJ/CPF e natureza). Históricos do mesmo modelo + conta + lado = uma pergunta; `revisado_ia` (migração 0008) evita perguntar de novo; CNPJ da IA só vale com dígito certo **e escrito no histórico**. Roda sozinho ao importar (sem IA, nada muda) e pelo botão **“🤖 Completar com a IA”** (mostra quantos estão pendentes).
- **Contas-chave pela prática da empresa** (`EVIDENCIAS`, no fim de `aprender()`): rendimento (crédito), tarifa, IOF e IR sobre aplicação (débito) — 2+ lançamentos e 70% na mesma conta analítica → a conta-chave passa a ser essa (confiança 90, justificativa “Pelo histórico da empresa…”); a escolha do usuário nunca é trocada.
- **Real (Casa Criança, IA de verdade, ≈ US$ 0,02):** 100 lançamentos revisados em 24 grupos; “REPASSE MUNICIPAL” → recebimento (10578 VERBA RECEBIDA A APLICAR) e “RENDIMENTO APLICAÇÃO FINANCEIRA” → recebimento (10586); provisões, notas fiscais a pagar e reconhecimento da receita ficaram internos (certo). Conta-chave **RENDIMENTO → 10586 RENDIMENTO A APLICAR** (antes: conta de receita pelo nome). Aprendido: 37 favorecidos, **2 clientes**, 6 palavras-chave.
- Testes (5 + 1 com IA real): 208 passando, ruff ok.


### 07/10/2026 — Etapa 1.7a concluída (Diário)
- `app/servicos/diario.py`: lê o Diário do Domínio em Excel (.xls/.xlsx, calamine) achando as colunas pelo título; cabeçalho Empresa / C.N.P.J. / Período; ignora TOTAL DO DIA / TOTAL DO MÊS / rodapé. **Monta as partidas:** Diário completo → soma as linhas seguidas até débito = crédito (1 × N); Diário filtrado (dia não fecha) → só junta duas linhas seguidas de lados opostos, mesmo valor e mesmo histórico; o resto fica com **um lado só** (migração 0007: conta de débito ou crédito pode ser nula) e o aviso pede o Diário com TODAS as contas.
- `importar_historico` aceita os dois formatos (`Movimento` comum); classificação → conta pelo plano (classificação repetida decide pela descrição, que no plano vem cortada em 40 letras); CNPJ do Diário diferente do da empresa → recusa; vazio → preenche **CNPJ e razão social com 🤖** e dispara a consulta pública.
- Lançamento com um lado só e histórico no modelo do extrato (“FAVORECIDO - NATUREZA - DOC”) = pagamento/recebimento pelo banco (aprende); o resto (provisão, nota fiscal a pagar) fica OUTRO, guardado para a IA (1.7b).
- **Sem contar em dobro:** o mesmo lançamento no lanctos.txt e no Diário é achado por lado (data, valor, histórico, D/C, conta); se o que já estava tinha um lado só, o novo **completa** o lado do banco.
- Consulta pública do CNPJ movida para `servicos/empresas.completar_pelo_cnpj` + `rotas/comum.avisar_consulta` (usada no cadastro e no Diário).
- **Resultado real (Casa Criança):** Diário filtrado (só Passivo) — 273 linhas, 251 partidas (229 com um lado só); junto com o lanctos 2026: **129 repetidos** (todos os pagamentos já estavam no lanctos), 122 novos (OUTRO); CNPJ 06.101.084/0001-36 e razão social preenchidos; ZERA ASSESSORIA continua com 6 ocorrências (não dobrou).
- Testes (9): Diários fictícios montados em `tests/diarios.py`; 203 testes passando, ruff ok.


### 07/10/2026 — Etapa 1.9 concluída (backup) + chave da IA ligada
- `app/servicos/backup.py`: `pg_dump -Fc` pelo contêiner + **conferência** (`pg_restore -l`, conta as tabelas); arquivos originais espelhados em `<pasta>/arquivos` (só copia os novos, nunca apaga). Nome `zera_AAAA-MM-DD_HH-MM-SS_<motivo>.dump` (automatico / manual / antes-de-restaurar); **30** por pasta.
- Dois destinos: `PASTA_BACKUP` (computador, padrão `dados/backups`) + `PASTA_BACKUP_NUVEM` (em branco = acha sozinho `<unidade>:\Meu Drive` / `My Drive` / pasta do usuário e cria `Backups ZERA CONTABIL MAX`; `NAO` desliga). Falha no Google Drive não derruba o backup do computador.
- Automático: o `INICIAR.bat` roda uma rotina em segundo plano que faz backup quando o último tem mais de 20 h (em cada pasta) e confere de novo a cada 30 min; falha aparece na janela e vai para o log (`BACKUP_FALHOU`). Uma trava impede dois backups juntos.
- **Restauração** (`RESTAURAR.bat` → `scripts/restaurar.py`): recusa se o sistema estiver aberto; lista os backups (computador + Google Drive), Enter = o mais recente, confirmação digitando RESTAURAR; guarda antes uma cópia “antes de restaurar” (só no computador); monta o backup num banco à parte (`<banco>_restaurando`) e só troca se deu certo (backup estragado não apaga nada); devolve os arquivos originais; roda as migrações; registra no log. Aceita um `.dump` como argumento (arrastar o arquivo sobre o .bat). Passo a passo em `docs/restaurar_backup.md` (inclui computador novo).
- Tela **Backup** (Supervisor): situação, destinos, como instalar o Google Drive, “Fazer backup agora”, lista. Tela inicial do Supervisor avisa backup com mais de 2 dias ou sem cópia no Google Drive.
- Testes (15): destinos, lista/limpeza, espelho, situação, **backup e restauração de verdade no PostgreSQL** (num banco à parte), backup estragado, tela e botão. Testes usam pastas temporárias e `PASTA_BACKUP_NUVEM=NAO`.
- Real: 1º backup feito (`dados/backups`, 11 tabelas) e `RESTAURAR.bat` testado de ponta a ponta no banco real (ainda vazio).
- Chave da API colocada no `.env` direto do arquivo do usuário (sem aparecer no chat); teste real ok com Haiku 4.5 e Sonnet 5.5.
- 194 testes passando, ruff ok.

### 07/10/2026 — Etapa 1.8 concluída (antes da 1.7, que espera o Diário)
- Tabelas `lancamento_historico` e `padrao` + perfil da IA na empresa (migração 0006).
- `app/servicos/lanctos.py`: leitura do lanctos.txt (§11.1) corrigindo os erros conhecidos (`28/01//2026`, `10595.`) com aviso; datas no futuro avisadas; arquivo de outra empresa (campo 8) recusado.
- `app/servicos/aprendizado.py`: separa favorecido / CNPJ (só com dígito válido) / natureza / documento; nomes normalizados (“DANIELA CORDEIRO **DE** OLIVEIRA” = “DANIELA CORDEIRO OLIVEIRA”); nomes diferentes com o mesmo CNPJ viram um só; lado do banco detectado (grupo Disponível + contas-chave + conta do ativo em metade das linhas); reimportar não duplica (marca por linha).
- **Regras do aprendizado:** vale o uso mais recente (2 ou mais seguidas na mesma conta = prática atual → Casa Criança: salários 331 → **187**, Quatai 10572 → **492**, PIS 494 → **191**); contas diferentes explicadas pela natureza não são ambíguas (SIEMACO: 10595/10596/10594, com os valores de cada uma — 910,00 = plano odontológico); ambíguo só quando nada explica; palavra-chave = natureza usada por 2+ favorecidos na mesma conta (“SALÁRIO MENSAL” → 187, “FÉRIAS” → 559, “RESCISÃO” → 560...); valores recorrentes com o mais recente primeiro.
- Conta usada como banco no histórico vira conta-chave (**BB conta 72637-0 → conta 8**, critério da Fase 1). Referência bancária agora sem agência (“BB conta 72637-0”), para o extrato cair na mesma conta-chave.
- Aprendizado em bloco = 1 evento no log (`sessao.info["auditoria_em_bloco"]`); as escolhas do usuário nos padrões são auditadas. Padrão aprendido que o histórico deixou de sustentar é apagado; o do usuário fica.
- Aba **3 Aprendizado**: importar histórico, avisos, recalcular, **perfil da empresa (IA, modelo rápido, sozinho após aprender)**, fornecedores/favorecidos (busca, “só os ambíguos”, trocar conta, desativar), palavras-chave (+ nova), clientes, pagamentos por conta. Barra do mês: **Aprendizado ✔**.
- **Resultado real (lanctos 2025 + 2026 da Casa Criança, 584 linhas):** 52 favorecidos, 12 palavras-chave, **nenhum ambíguo**.
- Login expirado volta para a mesma aba. `ruff` passou para 120 colunas.
- 179 testes passando (fixture anonimizada `tests/dados/lanctos_exemplo.txt`; plano de teste comum em `tests/planos.py`); banco real versão 0006, sem dados.
- **Como testar:** Casa Criança (código 230) com o plano importado → aba **3 Aprendizado** → envie `AMOSTRAS\historicos\lanctos_2025_casa_crianca.txt` e depois `AMOSTRAS\PLANILHA EXPORTAÇÃO\modelo exemplar da exportacao.txt` → veja os favorecidos, as palavras-chave e a aba 2 (Contas-chave: BB conta 72637-0 → 8).

### 06/10/2026 — Etapa 1.6 concluída
- Tabela `conta_chave` (Auditavel) + `empresa.usa_conta_individual` / `grupo_fornecedores` (migração 0005).
- `app/servicos/contas_chave.py`: natureza de cada conta pelo **nome** do grupo de 1º nível (Casa Criança: 3 = despesas, 4 = receitas; no outro plano é o contrário); 10 finalidades (rendimentos, IR retido, tarifas, IOF, juros pagos, fornecedores e clientes gerais, salários, FGTS, INSS) com palavras e pesos (negativos afastam: “RETIDO”, “PROVISÃO”...).
- Regra acha uma conta claramente melhor → aplica (95%/85%). Várias parecidas ou nenhuma → **IA (modelo forte) só para essas**, com as candidatas na pergunta e o plano inteiro no contexto (cache). **Conferência**: conta inexistente, sintética, de natureza errada ou palpite < 50% é recusada. Sem IA → a primeira do plano entre as parecidas, marcada “confira” (60%). Escolha do usuário (👤) nunca é sobrescrita.
- **Conta individual por fornecedor**: grupo de Fornecedores do passivo com ≥ 5 analíticas com nome → Casa Criança: sim, grupo **2.1.3.01** (205 contas). Editável no Cadastro (selo 🤖).
- **Contas bancárias**: `ligar_conta_bancaria(banco, agência, conta, tipo)` pontua número + banco + palavras do tipo. Casa Criança real: **BB 2180-6/72637-0 corrente → conta 8 (95%)**; **poupança → não encontrada** com o aviso da §3.2.1. Será chamada sozinha pela importação de extratos (Fase 2); hoje há o formulário “Ligar uma conta bancária agora”.
- Roda **sozinha ao importar/copiar o plano**; botão “Refazer a configuração automática”; troca com autocompletar (só analíticas). Botões de processos demorados mostram “aguarde” (`aguarde.js`, `data-aguarde`).
- Plano real da Casa Criança, só com regras: 187 salários, 192 FGTS, 191 INSS/PIS/IRRF/RAT, 31 IRRF a recuperar, 10001 fornecedores — **as mesmas do lanctos.txt do escritório**. Incertas (vão para a IA): rendimentos (5 candidatas), tarifas (8, uma por programa), juros pagos (2), IOF (nenhuma).
- 149 testes passando (+ `ia_real` da auto-configuração com o plano real, que roda quando a chave estiver no `.env`); ruff limpo. Banco real: versão 0005.
- **Como testar:** Casa Criança → aba **2 Plano de Contas** → (re)envie o plano → veja **Contas-chave** → em “Ligar uma conta bancária agora” use BB / 2180-6 / 72637-0 corrente e depois poupança.

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
