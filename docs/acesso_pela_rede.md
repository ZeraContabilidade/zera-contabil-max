# Usar o ZERA CONTÁBIL MAX nos outros computadores do escritório

Por padrão o sistema só abre **neste computador** (o que roda o `INICIAR.bat`). Para que os outros computadores
do escritório também usem, siga os passos abaixo. **O sistema continua fechado para a internet**: a liberação vale
só para a rede privada do escritório.

## Liberar (uma vez só)

1. Feche a janela preta do sistema (a do `INICIAR.bat`), se estiver aberta.
2. Na pasta do sistema, clique com o **botão direito** no `LIBERAR_REDE.bat` e escolha
   **“Executar como administrador”** (o Windows pede confirmação: clique em **Sim**).
3. A janela mostra o endereço para os outros computadores, por exemplo:
   `http://192.168.0.10:8000`. Anote.
4. Abra o sistema de novo pelo `INICIAR.bat`. A janela preta também mostra esse endereço.
5. Nos outros computadores, abra o navegador (Chrome ou Edge) e digite o endereço anotado.
   Cada pessoa entra com o **seu** usuário e senha.

## Se não abrir nos outros computadores

- **A rede do Windows precisa estar como “Rede privada”** neste computador:
  Configurações → Rede e Internet → clique na rede (Wi-Fi ou Ethernet) → **Tipo de perfil de rede: Privada**.
  (A liberação não vale em rede “Pública”, de propósito.)
- Este computador precisa estar **ligado e com o `INICIAR.bat` aberto** (a janela preta).
- Os computadores precisam estar na **mesma rede** do escritório.
- O endereço pode mudar se o roteador trocar o número deste computador. Se parar de abrir, veja o endereço novo na
  janela preta do `INICIAR.bat`. (Dica para o suporte de informática: fixar o IP deste computador no roteador.)
- Antivírus com firewall próprio (não o do Windows) pode bloquear: peça ao suporte para liberar a porta **8000** só
  para a rede local.

## Fechar de novo (voltar a só este computador)

Botão direito no `FECHAR_REDE.bat` → **“Executar como administrador”**, e depois feche e abra o `INICIAR.bat`.

## Segurança

- Nunca abra a porta 8000 no roteador para a internet. Para usar de fora do escritório, a Fase 4 prevê a nuvem
  com HTTPS.
- Cada pessoa usa o próprio usuário; tudo o que é feito fica no **Log** com o nome de quem fez.
- O banco de dados continua acessível só neste computador (porta 5433 fechada para a rede).
