# Instalar e usar o ZERA CONTÁBIL MAX em outra máquina

Primeiro, escolha a sua situação:

| Situação | O que fazer |
|---|---|
| **A.** O sistema continua neste computador e **outras pessoas do escritório** querem usar nos computadores delas | [Parte A](#a-usar-de-outro-computador-do-escritório) — não precisa instalar nada nos outros computadores |
| **B.** O sistema vai **mudar de computador** (computador novo, servidor, o antigo estragou) levando todos os dados | [Parte B](#b-mudar-o-sistema-para-outro-computador-levando-os-dados) |
| **C.** Instalar **do zero**, sem dados (outro escritório, computador de teste) | [Parte C](#c-instalar-do-zero-sem-dados) |

> **O programa está no GitHub (repositório PRIVADO):** <https://github.com/ZeraContabilidade/zera-contabil-max>.
> Só a conta **ZeraContabilidade** (e quem ela convidar) enxerga. Lá vai **só o programa**: o `sistema\.env` (senhas e
> chave da IA), a pasta `dados` (backups, extratos) e as amostras **nunca** vão para o GitHub — os dados viajam pelo
> backup (pendrive ou Google Drive). Veja [Baixar pelo GitHub](#baixar-pelo-github).

> **Importante:** os dados ficam em **um computador só** (o que roda o `INICIAR.bat`). Não use o sistema instalado em dois
> computadores ao mesmo tempo achando que eles se falam: cada instalação tem o seu próprio banco de dados.
> Para várias pessoas trabalharem juntas, use a **Parte A**.

**Onde fica cada coisa:** o `INICIAR.bat` fica na pasta principal (ex.: `C:\ZERA CONTABIL MAX`); as outras ferramentas
(`INSTALAR.bat`, `ATUALIZAR.bat`, `RESTAURAR_BACKUP.bat`, `LIBERAR_REDE.bat`, `CONFIGURAR_IA.bat` e a pasta
`Preparar computador`) ficam na pasta **`Ferramentas`**.

---

## A. Usar de outro computador do escritório

O sistema fica instalado em um computador (o “servidor”, este aqui) e os outros só abrem pelo navegador.

**No computador onde o sistema está instalado (uma vez só):**

1. Feche a janela preta do sistema (a do `INICIAR.bat`), se estiver aberta.
2. Na pasta `Ferramentas`, clique com o **botão direito** no `LIBERAR_REDE.bat` → **Executar como administrador** → **Sim**.
3. A janela mostra o endereço para os outros computadores, por exemplo `http://192.168.0.10:8000`. **Anote.**
4. Abra o sistema de novo pelo `INICIAR.bat` (a janela preta também mostra esse endereço).

**Em cada um dos outros computadores:**

5. Abra o **Chrome** ou o **Edge** e digite o endereço anotado (ex.: `http://192.168.0.10:8000`).
6. Entre com o **usuário e a senha da pessoa** (o Supervisor cadastra cada um no menu **Usuários**).
7. Dica: crie um favorito ou um atalho na área de trabalho para esse endereço.

**Para funcionar no dia a dia:** o computador do sistema precisa estar **ligado e com o `INICIAR.bat` aberto**, e todos na
mesma rede do escritório. Se não abrir, veja o manual **3 - Usar em outros computadores** (rede “Privada”, endereço que
mudou, antivírus). Para desfazer: botão direito no `Ferramentas\FECHAR_REDE.bat` → Executar como administrador.

---

## B. Mudar o sistema para outro computador (levando os dados)

### No computador ANTIGO

1. Abra o sistema e entre como Supervisor → menu **Backup** → **Fazer backup agora**. Espere a mensagem de sucesso.
2. **Feche** a janela preta do sistema (a do `INICIAR.bat`).
3. Copie para um **pendrive** (ou para uma pasta da rede) a **pasta do sistema inteira** (`C:\ZERA CONTABIL MAX`):
   - a pasta `dados` vai junto — é nela que estão os backups (`dados\backups`, com os arquivos `zera_….dump` e a pasta
     `arquivos`);
   - o arquivo **`sistema\.env`** vai junto: ele tem a **chave da IA** e as senhas do banco. **Guarde o pendrive com
     cuidado** e apague a cópia depois que terminar;
   - as pastas ocultas (como a `.venv`) podem ir junto: o `INSTALAR.bat` refaz o que não servir no computador novo.
4. **Não use mais** o sistema no computador antigo depois do backup (o que for feito nele não vai para o novo).

### No computador NOVO

5. **Preparar o computador** (Windows 10 ou 11, 64 bits, com internet; recomendado 8 GB de memória):
   - Copie a pasta do pendrive para `C:\ZERA CONTABIL MAX` (pode ser outra pasta, se preferir) — ou baixe o programa
     pelo GitHub (veja [Baixar pelo GitHub](#baixar-pelo-github)) e copie do pendrive só a pasta `dados` e o arquivo
     `sistema\.env` (para o mesmo lugar).
   - Dê dois cliques em `Ferramentas\Preparar computador\PREPARAR_COMPUTADOR.bat` e clique **Sim** quando o Windows
     pedir permissão. Ele instala o **Python** e o **Docker Desktop** (e também ferramentas usadas na manutenção).
   - **Reinicie o computador.**
   - Abra o **Docker Desktop** uma vez pelo menu Iniciar e aceite os termos (pode pular o login da Docker).
   > Se preferir instalar à mão: **Python 3.12 ou mais novo** (marque “Add python.exe to PATH”) e **Docker Desktop**.
   > **Windows 11 com “Controle de Aplicativo Inteligente” ligado** (Segurança do Windows → Controle de aplicativos e do
   > navegador): ele bloqueia partes do Python que o sistema usa e não deixa liberar arquivo por arquivo — o sistema
   > **não roda** com ele ligado. Ou use a **Parte A** (não instala nada no outro computador), ou desligue-o nesse
   > computador antes do passo 6 (decisão de quem cuida da segurança dos computadores do escritório; o antivírus do
   > Windows continua ligado).
6. Na pasta `Ferramentas`, dê dois cliques no **`INSTALAR.bat`** e espere “Instalação concluída!”
   (ele aproveita o `sistema\.env` que veio do pendrive e cria o banco de dados vazio).
7. Ainda na pasta `Ferramentas`, dê dois cliques no **`RESTAURAR_BACKUP.bat`**: aparece a lista de backups (os que vieram
   em `dados\backups`). Tecle **Enter** para o mais recente e digite **RESTAURAR** para confirmar. Espere “Pronto!”.
   - Se os backups estiverem em outro lugar, arraste o arquivo `zera_….dump` para cima do `RESTAURAR_BACKUP.bat`
     — deixe a pasta `arquivos` **ao lado** do arquivo `.dump`, para os extratos e planos originais voltarem também.
8. Dê dois cliques no **`INICIAR.bat`** (pasta principal). O navegador abre o sistema: entre com os **mesmos usuários e
   senhas** de antes. Confira na lista de empresas se está tudo lá.
9. Se não trouxe o `.env` no pendrive: na pasta `Ferramentas`, dê dois cliques no **`CONFIGURAR_IA.bat`**, cole a chave
   da IA (ela não aparece na tela) e tecle Enter. Depois feche e abra o `INICIAR.bat` de novo.
10. Para os outros computadores usarem, faça a **Parte A** neste computador novo (a liberação do Firewall é por computador).
11. Recomendado: instale o **Google Drive para computador** e entre na conta do escritório — o backup diário passa a ter
    uma cópia lá sozinho (veja o manual **2 - Backup e restauração**).
12. Atalho: botão direito no `INICIAR.bat` → **Enviar para** → **Área de trabalho (criar atalho)**.

---

## C. Instalar do zero (sem dados)

1. Baixe o programa pelo GitHub (veja [Baixar pelo GitHub](#baixar-pelo-github)) — ou copie a pasta do sistema
   **sem** a pasta `dados` e **sem** o arquivo `sistema\.env`.
2. Faça os passos **5 e 6** da Parte B (preparar o computador e `Ferramentas\INSTALAR.bat`): o `INSTALAR.bat` cria um
   `.env` novo com senhas novas.
3. Na pasta `Ferramentas`, dê dois cliques no **`CONFIGURAR_IA.bat`** e cole a chave da IA (sem ela o sistema funciona
   só com regras e aprendizado).
4. Dê dois cliques no **`INICIAR.bat`**. Na primeira vez aparece **Primeiro acesso**: cadastre o **Supervisor**
   (nome, usuário e senha).
5. Pronto: cadastre os usuários (menu **Usuários**) e as empresas (**+ Nova empresa**). O roteiro do mês está no
   manual **1 - Como usar no dia a dia**.

---

## Baixar pelo GitHub

O repositório é **privado**: é preciso entrar na conta **ZeraContabilidade** do GitHub.

### Jeito 1 — com o Git (recomendado: depois dá para atualizar com um clique)

1. Instale o Git em <https://git-scm.com> e o GitHub CLI em <https://cli.github.com> (ou, se já tem a pasta do sistema,
   rode antes o `Ferramentas\Preparar computador\PREPARAR_COMPUTADOR.bat`, que instala os dois).
2. Abra o **PowerShell** e entre na conta do GitHub (abre o navegador para confirmar):
   ```
   gh auth login
   ```
   Escolha **GitHub.com** → **HTTPS** → **Login with a web browser** e siga as instruções.
3. Baixe o sistema para `C:\ZERA CONTABIL MAX`:
   ```
   gh repo clone ZeraContabilidade/zera-contabil-max "C:\ZERA CONTABIL MAX"
   ```
4. Continue pela **Parte B** (passo 5 em diante) ou **Parte C** (passo 2 em diante).

**Atualizar depois** (quando houver melhorias no sistema): feche a janela preta do sistema e, na pasta `Ferramentas`, dê
dois cliques no **`ATUALIZAR.bat`**. Ele baixa a versão nova do GitHub e reinstala as bibliotecas; **os dados e o
`sistema\.env` não são alterados**. Depois abra pelo `INICIAR.bat` (o banco é atualizado sozinho ao abrir).

### Jeito 2 — sem instalar o Git (baixar o ZIP)

1. Entre em <https://github.com> com a conta **ZeraContabilidade** e abra o repositório **zera-contabil-max**.
2. Botão verde **Code** → **Download ZIP**.
3. Extraia o ZIP e renomeie a pasta extraída (`zera-contabil-max-main`) para `C:\ZERA CONTABIL MAX`.
4. Continue pela **Parte B** ou **Parte C**.

Pelo ZIP o `ATUALIZAR.bat` não funciona: para atualizar, baixe o ZIP de novo e copie por cima **sem apagar** a pasta
`dados` nem o arquivo `sistema\.env`.

---

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| “Não encontrei o Python 3.12 ou mais novo” | Rode o `PREPARAR_COMPUTADOR.bat`, reinicie e rode o `INSTALAR.bat` de novo. |
| “O Controle de Aplicativo Inteligente bloqueou…” / “Parte deste aplicativo foi bloqueada” | É a proteção do Windows 11 bloqueando partes do Python que o sistema usa (exceção no antivírus não resolve). Se o outro computador só vai **usar** o sistema, faça a **Parte A** (nada é instalado nele). Se o sistema precisa **rodar** nele, o Controle de Aplicativo Inteligente tem que ficar desligado nesse computador (veja a nota do passo 5). |
| O `INSTALAR.bat` ou o `INICIAR.bat` fica esperando o Docker | Abra o **Docker Desktop** pelo menu Iniciar, espere ficar “Running” e tente de novo. Se pedir para ativar a virtualização/WSL, reinicie o computador. |
| “O sistema ainda não foi instalado” | Na pasta `Ferramentas`, dê dois cliques no `INSTALAR.bat`. |
| “Banco de dados desligado” no navegador | Feche a janela preta e abra de novo pelo `INICIAR.bat` (ele liga o Docker e o banco sozinho). |
| O `RESTAURAR_BACKUP.bat` não acha nenhum backup | Confira se os arquivos `zera_….dump` estão em `dados\backups` da pasta do sistema, ou arraste o `.dump` para cima do `RESTAURAR_BACKUP.bat`. |
| Entrou, mas as empresas não aparecem | O backup não foi restaurado: feche o sistema e faça o passo 7 da Parte B. |
| Os outros computadores não abrem o endereço | Veja a Parte A e o manual **3 - Usar em outros computadores**. |
| O `ATUALIZAR.bat` diz que não conseguiu baixar | Confira a internet e o login no GitHub (`gh auth login` no PowerShell). |
| O GitHub mostra “404” ao abrir o repositório | Você não está na conta **ZeraContabilidade** (o repositório é privado). |

> **Nunca** troque as senhas `POSTGRES_…` dentro do `sistema\.env` depois que o banco foi criado: o sistema deixa de
> conectar.
