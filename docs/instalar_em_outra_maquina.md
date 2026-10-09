# Instalar e usar o ZERA CONTÁBIL MAX em outra máquina

Primeiro, escolha a sua situação:

| Situação | O que fazer |
|---|---|
| **A.** O sistema continua neste computador e **outras pessoas do escritório** querem usar nos computadores delas | [Parte A](#a-usar-de-outro-computador-do-escritório) — não precisa instalar nada nos outros computadores |
| **B.** O sistema vai **mudar de computador** (computador novo, servidor, o antigo estragou) levando todos os dados | [Parte B](#b-mudar-o-sistema-para-outro-computador-levando-os-dados) |
| **C.** Instalar **do zero**, sem dados (outro escritório, computador de teste) | [Parte C](#c-instalar-do-zero-sem-dados) |

> **O programa está no GitHub (repositório PRIVADO):** <https://github.com/ZeraContabilidade/zera-contabil-max>.
> Só a conta **ZeraContabilidade** (e quem ela convidar) enxerga. Lá vai **só o programa**: o `.env` (senhas e chave
> da IA), a pasta `dados` (banco, backups, extratos) e a `AMOSTRAS` **nunca** vão para o GitHub — os dados viajam pelo
> backup (pendrive ou Google Drive). Veja [Baixar pelo GitHub](#baixar-pelo-github).

> **Importante:** os dados ficam em **um computador só** (o que roda o `INICIAR.bat`). Não use o sistema instalado em dois
> computadores ao mesmo tempo achando que eles se falam: cada instalação tem o seu próprio banco de dados.
> Para várias pessoas trabalharem juntas, use a **Parte A**.

---

## A. Usar de outro computador do escritório

O sistema fica instalado em um computador (o “servidor”, este aqui) e os outros só abrem pelo navegador.

**No computador onde o sistema está instalado (uma vez só):**

1. Feche a janela preta do sistema (a do `INICIAR.bat`), se estiver aberta.
2. Na pasta do sistema, clique com o **botão direito** no `LIBERAR_REDE.bat` → **Executar como administrador** → **Sim**.
3. A janela mostra o endereço para os outros computadores, por exemplo `http://192.168.0.10:8000`. **Anote.**
4. Abra o sistema de novo pelo `INICIAR.bat` (a janela preta também mostra esse endereço).

**Em cada um dos outros computadores:**

5. Abra o **Chrome** ou o **Edge** e digite o endereço anotado (ex.: `http://192.168.0.10:8000`).
6. Entre com o **usuário e a senha da pessoa** (o Supervisor cadastra cada um no menu **Usuários**).
7. Dica: crie um favorito ou um atalho na área de trabalho para esse endereço.

**Para funcionar no dia a dia:** o computador do sistema precisa estar **ligado e com o `INICIAR.bat` aberto**, e todos na
mesma rede do escritório. Se não abrir, veja [acesso_pela_rede.md](acesso_pela_rede.md) (rede “Privada”, endereço que
mudou, antivírus). Para desfazer: botão direito no `FECHAR_REDE.bat` → Executar como administrador.

---

## B. Mudar o sistema para outro computador (levando os dados)

### No computador ANTIGO

1. Abra o sistema e entre como Supervisor → menu **Backup** → **Fazer backup agora**. Espere a mensagem de sucesso.
2. **Feche** a janela preta do sistema (a do `INICIAR.bat`).
3. Copie para um **pendrive** (ou para uma pasta da rede):
   - a **pasta do sistema inteira** (`C:\ZERA CONTABIL MAX`), **sem** a subpasta `.venv` (ela é refeita na instalação);
     a subpasta `dados` pode ir junto — é nela que estão os backups (`dados\backups`, com os arquivos `zera_….dump`
     e a pasta `arquivos`).
   - O arquivo **`.env`** vai junto com a pasta: ele tem a **chave da IA** e as senhas do banco. **Guarde o pendrive com
     cuidado** e apague a cópia depois que terminar.
4. **Não use mais** o sistema no computador antigo depois do backup (o que for feito nele não vai para o novo).

### No computador NOVO

5. **Preparar o computador** (Windows 10 ou 11, 64 bits, com internet; recomendado 8 GB de memória):
   - Copie a pasta do pendrive para `C:\ZERA CONTABIL MAX` (pode ser outra pasta, se preferir) — ou baixe o programa
     pelo GitHub (veja [Baixar pelo GitHub](#baixar-pelo-github)) e copie do pendrive só a pasta `dados` e o `.env`.
   - Dê dois cliques em `ferramentas\preparar_computador\PREPARAR_COMPUTADOR.bat` e clique **Sim** quando o Windows
     pedir permissão. Ele instala o **Python** e o **Docker Desktop** (e também ferramentas usadas na manutenção).
   - **Reinicie o computador.**
   - Abra o **Docker Desktop** uma vez pelo menu Iniciar e aceite os termos (pode pular o login da Docker).
   > Se preferir instalar à mão: **Python 3.12 ou mais novo** (marque “Add python.exe to PATH”) e **Docker Desktop**.
6. Na pasta do sistema, dê dois cliques no **`INSTALAR.bat`** e espere “Instalação concluída!”
   (ele aproveita o `.env` que veio do pendrive e cria o banco de dados vazio).
7. Dê dois cliques no **`RESTAURAR.bat`**: aparece a lista de backups (os que vieram em `dados\backups`).
   Tecle **Enter** para o mais recente e digite **RESTAURAR** para confirmar. Espere “Pronto!”.
   - Se os backups estiverem em outro lugar, arraste o arquivo `zera_….dump` para cima do `RESTAURAR.bat`
     — deixe a pasta `arquivos` **ao lado** do arquivo `.dump`, para os extratos e planos originais voltarem também.
8. Dê dois cliques no **`INICIAR.bat`**. O navegador abre o sistema: entre com os **mesmos usuários e senhas** de antes.
   Confira na lista de empresas se está tudo lá.
9. Se não trouxe o `.env` no pendrive: abra o arquivo `.env` da pasta do sistema no **Bloco de Notas**, cole a chave da
   IA depois de `ANTHROPIC_API_KEY=` (sem espaços nem aspas), salve, feche e abra o `INICIAR.bat` de novo.
10. Para os outros computadores usarem, faça a **Parte A** neste computador novo (a liberação do Firewall é por computador).
11. Recomendado: instale o **Google Drive para computador** e entre na conta do escritório — o backup diário passa a ter
    uma cópia lá sozinho (veja [restaurar_backup.md](restaurar_backup.md)).
12. Atalho: botão direito no `INICIAR.bat` → **Enviar para** → **Área de trabalho (criar atalho)**.

---

## C. Instalar do zero (sem dados)

1. Baixe o programa pelo GitHub (veja [Baixar pelo GitHub](#baixar-pelo-github)) — ou copie a pasta do sistema
   **sem** as subpastas `.venv` e `dados` e **sem** o arquivo `.env`.
2. Faça os passos **5 e 6** da Parte B (preparar o computador e `INSTALAR.bat`): o `INSTALAR.bat` cria um `.env` novo
   com senhas novas.
3. Abra o `.env` no Bloco de Notas e cole a chave da IA em `ANTHROPIC_API_KEY=` (sem ela o sistema funciona só com regras
   e aprendizado).
4. Dê dois cliques no **`INICIAR.bat`**. Na primeira vez aparece **Primeiro acesso**: cadastre o **Supervisor**
   (nome, usuário e senha).
5. Pronto: cadastre os usuários (menu **Usuários**) e as empresas (**+ Nova empresa**). O roteiro do mês está em
   [como_usar.md](como_usar.md).

---

## Baixar pelo GitHub

O repositório é **privado**: é preciso entrar na conta **ZeraContabilidade** do GitHub.

### Jeito 1 — com o Git (recomendado: depois dá para atualizar com um clique)

1. No computador novo, rode `ferramentas\preparar_computador\PREPARAR_COMPUTADOR.bat` **antes** (ele instala o Git e o
   GitHub CLI) — se ainda não tem a pasta, instale o Git em <https://git-scm.com> e o GitHub CLI em <https://cli.github.com>.
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

**Atualizar depois** (quando houver melhorias no sistema): feche a janela preta do sistema e dê dois cliques no
**`ATUALIZAR.bat`**. Ele baixa a versão nova do GitHub e reinstala as bibliotecas; **os dados e o `.env` não são
alterados**. Depois abra pelo `INICIAR.bat` (o banco é atualizado sozinho ao abrir).

### Jeito 2 — sem instalar o Git (baixar o ZIP)

1. Entre em <https://github.com> com a conta **ZeraContabilidade** e abra o repositório **zera-contabil-max**.
2. Botão verde **Code** → **Download ZIP**.
3. Extraia o ZIP e renomeie a pasta extraída (`zera-contabil-max-main`) para `C:\ZERA CONTABIL MAX`.
4. Continue pela **Parte B** ou **Parte C**.

Pelo ZIP o `ATUALIZAR.bat` não funciona: para atualizar, baixe o ZIP de novo e copie por cima **sem apagar** a pasta
`dados` nem o arquivo `.env`.

---

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| “Não encontrei o Python 3.12 ou mais novo” | Rode o `PREPARAR_COMPUTADOR.bat`, reinicie e rode o `INSTALAR.bat` de novo. |
| O `INSTALAR.bat` ou o `INICIAR.bat` fica esperando o Docker | Abra o **Docker Desktop** pelo menu Iniciar, espere ficar “Running” e tente de novo. Se pedir para ativar a virtualização/WSL, reinicie o computador. |
| “Banco de dados desligado” no navegador | Feche a janela preta e abra de novo pelo `INICIAR.bat` (ele liga o Docker e o banco sozinho). |
| O `RESTAURAR.bat` não acha nenhum backup | Confira se os arquivos `zera_….dump` estão em `dados\backups` da pasta do sistema, ou arraste o `.dump` para cima do `RESTAURAR.bat`. |
| Entrou, mas as empresas não aparecem | O backup não foi restaurado: feche o sistema e faça o passo 7 da Parte B. |
| Os outros computadores não abrem o endereço | Veja a Parte A e [acesso_pela_rede.md](acesso_pela_rede.md). |
| O `ATUALIZAR.bat` diz que não conseguiu baixar | Confira a internet e o login no GitHub (`gh auth login` no PowerShell). |
| O GitHub mostra “404” ao abrir o repositório | Você não está na conta **ZeraContabilidade** (o repositório é privado). |

> **Nunca** troque as senhas `POSTGRES_…` dentro do `.env` depois que o banco foi criado: o sistema deixa de conectar.
