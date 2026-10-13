# Roteiro do mês no ZERA CONTÁBIL MAX

Para cada empresa, uma vez por mês. A barra no topo da empresa mostra onde você está:
**Plano → Aprendizado → Extrato → Revisão → Exportado**.

## Uma vez só, ao cadastrar a empresa (Supervisor)

1. **Empresas → + Nova empresa**: basta o código da empresa no Domínio; o CNPJ completa o resto.
   - **Filial:** cada filial é um cadastro. Em “Código da empresa no Domínio” vai o código da **matriz** e em
     “Código da filial” o código da filial no Domínio. O `lanctos.txt` dessa filial sai com o código da filial
     (coluna 8 do arquivo).
2. **Plano de Contas**: envie o plano exportado do Domínio. O sistema descobre sozinho as contas-chave
   (banco, rendimentos, tarifas…) e se a empresa usa conta individual por fornecedor.
3. **Aprendizado**: envie o histórico (o `lanctos.txt` dos anos anteriores e/ou o Diário em Excel).
   É daqui que o sistema aprende onde a empresa lança cada fornecedor.

## Todo mês

1. Escolha o **mês** no canto da tela da empresa.
2. **Extratos**: arraste os extratos do mês (PDF, OFX ou Excel; pode ser vários de uma vez). O sistema confere o saldo,
   não duplica nada e já classifica cada movimento (regras + IA).
3. **Revisão**: a tela já abre só no que precisa de atenção.
   - Troque a conta digitando o código ou parte do nome (ex.: “agua” ou “355”) e clique em **Salvar** — o sistema
     aprende para o mês seguinte.
   - **Aprovar** aceita a sugestão; **Ignorar** deixa sem lançamento.
   - Para várias linhas: marque as caixinhas e use a barra acima da grade.
   - Fornecedor sem conta no plano (empresas com conta individual): **Fornecedor novo** → ele vai para a lista
     “Fornecedores a cadastrar no Domínio” (baixe em Excel, crie as contas no Domínio e reimporte o plano).
4. **Exportar**: confira o total por conta e clique em **Gerar lanctos.txt**. Baixe o arquivo e importe no Domínio.
   As linhas exportadas ficam travadas; só o Supervisor reabre (com o motivo).

## Por período (ex.: o ano todo de uma vez)

Para trabalhar vários meses juntos — por exemplo, de 01/2025 a 12/2025 — e gerar **um só** `lanctos.txt`:

1. Ao lado do mês, clique em **Vários meses**, escolha **De** (ex.: janeiro de 2025) e **Até** (ex.: dezembro de 2025)
   e clique em **Ver período**. O período fica escolhido em todas as telas até você trocar.
2. **Extratos**: arraste os extratos de todos os meses (pode ser de uma vez). A lista mostra o período inteiro.
3. **Revisão**: mostra as linhas do período inteiro. “Aplicar às parecidas” vale para o período todo.
4. **Exportar**: gera um único arquivo com todos os meses (ex.: `lanctos_230_2025-01_a_2025-12.txt`).
5. Para voltar a um mês só, clique em **Um mês só**.

A exportação automática (quando ligada no cadastro) continua sendo feita mês a mês.

## Atalhos que economizam tempo

| Tecla | O que faz |
|---|---|
| **Ctrl + K** (ou “Ir para…” no menu) | Abre qualquer empresa, aba ou tela digitando parte do nome — ex.: “creche rev” abre a Revisão da Creche |
| **?** | Mostra todos os atalhos |
| **/** | Vai para a busca da tela |
| **1** a **5** (dentro da empresa) | Plano · Aprendizado · Extratos · Revisão · Exportar · **0** = Cadastro |
| **J / K** ou **↓ / ↑** (Revisão) | Desce / sobe de linha |
| **Enter** (Revisão) | Vai para a conta da linha; Enter de novo grava e passa para a próxima |
| **A** / **I** / **X** (Revisão) | Aprovar / Ignorar / Marcar a linha |

Na tela **Empresas**, o cartão **Próximo passo sugerido** leva direto para a tarefa mais adiantada (primeiro as
empresas pelas quais você é responsável).

## Abrir como aplicativo (recomendado)

O sistema pode ficar na barra de tarefas com o emblema da Zera, abrindo em janela própria (sem a barra de endereço):

- **Microsoft Edge:** com o sistema aberto, menu **⋯** → **Aplicativos** → **Instalar este site como um aplicativo**.
- **Google Chrome:** menu **⋮** → **Transmitir, salvar e compartilhar** → **Instalar página como app…**
  (nos computadores que acessam pela rede, o Chrome pode oferecer **Criar atalho…** — marque **Abrir como janela**).

Use o Chrome ou o Edge **atualizados**: as trocas de tela suaves só aparecem neles.

## Para o Supervisor

- **Painel**: todas as empresas no mês — onde cada uma parou, pendências, % classificado sozinho, correções e quem
  exportou.
- **IA**: quanto a IA gastou e quantas linhas resolveu.
- **Backup**: automático uma vez por dia; restaurar pelo `Ferramentas\RESTAURAR_BACKUP.bat`
  (veja o manual **2 - Backup e restauração**).
- **Rede do escritório**: `Ferramentas\LIBERAR_REDE.bat` (veja o manual **3 - Usar em outros computadores**).
- **Outra máquina** (mudar o sistema de computador ou instalar do zero): veja o manual **4 - Instalar em outra máquina**.
- **Chave da IA**: para colocar ou trocar, `Ferramentas\CONFIGURAR_IA.bat` (a chave não aparece na tela).
- **Guarda**: extratos, planos e arquivos gerados ficam guardados por 5 anos e depois são apagados sozinhos
  (o registro fica no Log).

## O que tem na pasta do sistema

| Pasta ou arquivo | Para que serve |
|---|---|
| `INICIAR.bat` | Abre o sistema (dois cliques). É o único que você usa no dia a dia. |
| `Ferramentas` | Instalar, atualizar, restaurar backup, liberar a rede, chave da IA, preparar um computador novo. |
| `Manuais` | Estes passo a passo. |
| `dados` | Os dados do escritório: backups e arquivos enviados. **Não apague nem mexa.** |
| `sistema` | O programa em si. Não precisa abrir. |
