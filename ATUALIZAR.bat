@echo off
setlocal
cd /d "%~dp0"
title ZERA CONTABIL MAX - Atualizar
echo ==================================================
echo   ZERA CONTABIL MAX - Atualizar pelo GitHub
echo ==================================================
echo.

where git >nul 2>&1
if errorlevel 1 goto sem_git
if not exist ".git" goto sem_github

if /i not "%~1"=="/sem-pausa" (
  echo Feche a janela preta do sistema ^(a do INICIAR.bat^) antes de continuar.
  echo Seus dados ^(banco, backups, .env^) NAO sao alterados pela atualizacao.
  pause
)

echo Buscando a versao mais nova no GitHub...
git pull --ff-only
if errorlevel 1 goto erro_pull

call "%~dp0INSTALAR.bat" /sem-pausa
if errorlevel 1 goto erro_instalar

echo.
echo ==================================================
echo   Sistema atualizado! Abra pelo INICIAR.bat.
echo ==================================================
goto fim

:sem_git
echo [ERRO] O Git nao esta instalado neste computador.
echo Rode ferramentas\preparar_computador\PREPARAR_COMPUTADOR.bat, reinicie e tente de novo.
goto fim_erro

:sem_github
echo [ERRO] Esta pasta nao foi baixada com o Git ^(por exemplo, veio de um ZIP ou pendrive^).
echo Para atualizar, baixe de novo como explica docs\instalar_em_outra_maquina.md.
goto fim_erro

:erro_pull
echo.
echo [ERRO] Nao consegui baixar a atualizacao. Confira a internet e se esta conectado ao GitHub
echo ^(no PowerShell: gh auth login^). Se aparecer que ha arquivos alterados nesta pasta, peca ajuda ao suporte.
goto fim_erro

:erro_instalar
echo A atualizacao baixou, mas a instalacao das bibliotecas nao terminou. Rode o INSTALAR.bat de novo.
goto fim_erro

:fim_erro
if /i not "%~1"=="/sem-pausa" pause
exit /b 1

:fim
if /i not "%~1"=="/sem-pausa" pause
exit /b 0
