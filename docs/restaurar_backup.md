# Backup e restauração — passo a passo

## Como o backup funciona

- O sistema faz **um backup por dia, sozinho**: ao abrir pelo `INICIAR.bat` e, se ficar aberto, a cada 24 horas.
- Cada backup é uma cópia **completa** do banco de dados (empresas, planos, aprendizado, usuários, log…)
  mais os **arquivos originais** enviados (planos, Diários, extratos).
- As cópias ficam em dois lugares:
  1. **Neste computador:** pasta `dados\backups` do sistema;
  2. **Google Drive:** pasta `Meu Drive\Backups ZERA CONTABIL MAX` (quando o Google Drive para computador está instalado).
- Cada pasta guarda os **30 backups mais recentes** (os mais antigos são apagados sozinhos).
- A tela **Backup** (menu do Supervisor) mostra a situação, a lista de backups e o botão **Fazer backup agora**.
  Se o último backup tiver mais de 2 dias, a tela inicial avisa.

> As pastas de backup têm dados dos clientes: não compartilhe a pasta do Google Drive com ninguém de fora do escritório.

## Ligar a cópia no Google Drive

1. Baixe e instale o **Google Drive para computador**: <https://www.google.com/drive/download/>.
2. Entre com a conta Google do escritório.
3. Espere aparecer no Explorador de Arquivos a unidade **Google Drive (G:)** com a pasta **Meu Drive**.
4. Pronto. No próximo backup o sistema encontra a pasta sozinho e cria `Backups ZERA CONTABIL MAX` dentro dela
   (para não esperar: tela **Backup → Fazer backup agora**).

Para usar outra pasta, abra o arquivo `.env` no Bloco de Notas e preencha, por exemplo:
`PASTA_BACKUP_NUVEM=G:\Meu Drive\Minha pasta de backups`. Feche e abra o sistema de novo.

## Restaurar um backup (mesmo computador)

Use quando algo foi apagado ou alterado por engano e você quer voltar os dados de um dia anterior.

1. **Feche a janela preta do sistema** (a do `INICIAR.bat`).
2. Dê dois cliques no **`RESTAURAR.bat`**, na pasta do sistema.
3. Aparece a lista de backups, do mais recente para o mais antigo, com data, hora e onde está (computador ou Google Drive).
4. Digite o **número** do backup e tecle Enter (só Enter = o mais recente).
5. Digite **RESTAURAR** para confirmar.
6. O sistema primeiro guarda uma **cópia dos dados atuais** (tipo “Antes de restaurar”) e depois troca os dados.
   Se o backup escolhido estiver estragado, **nada é alterado** e aparece uma mensagem pedindo outro.
7. Quando aparecer “Pronto!”, abra o sistema pelo `INICIAR.bat`.

Mudou de ideia? Rode o `RESTAURAR.bat` de novo e escolha o backup “Antes de restaurar”.

## Restaurar num computador novo (o antigo estragou)

1. Prepare o computador: `ferramentas\preparar_computador\PREPARAR_COMPUTADOR.bat`.
2. Copie a pasta do sistema (do GitHub ou de um pendrive) e rode o **`INSTALAR.bat`**.
3. Instale o **Google Drive para computador**, entre na conta do escritório e espere a pasta
   `Meu Drive\Backups ZERA CONTABIL MAX` aparecer.
4. Dê dois cliques no **`RESTAURAR.bat`** e escolha o backup mais recente (Enter), depois digite **RESTAURAR**.
5. Coloque de novo a chave da IA no arquivo `.env` (linha `ANTHROPIC_API_KEY=`): por segurança ela **não** vai para o backup.
6. Abra o sistema pelo `INICIAR.bat` e entre com os mesmos usuários e senhas de antes.

## Restaurar um arquivo específico

Se você tem um arquivo `.dump` em outro lugar (pendrive, e-mail…), arraste o arquivo para cima do `RESTAURAR.bat`
— ou rode no Prompt de Comando, dentro da pasta do sistema: `RESTAURAR.bat "caminho\do\arquivo.dump"`.
