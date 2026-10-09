# Roteiro do mês no ZERA CONTÁBIL MAX

Para cada empresa, uma vez por mês. A barra no topo da empresa mostra onde você está:
**Plano → Aprendizado → Extrato → Revisão → Exportado**.

## Uma vez só, ao cadastrar a empresa (Supervisor)

1. **Empresas → + Nova empresa**: basta o código da empresa no Domínio; o CNPJ completa o resto.
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
