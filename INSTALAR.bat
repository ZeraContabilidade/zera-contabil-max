@echo off
setlocal
cd /d "%~dp0"
title ZERA CONTABIL MAX - Instalacao
echo ==================================================
echo   ZERA CONTABIL MAX - Instalacao do sistema
echo ==================================================
echo.

python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if errorlevel 1 goto erro_python

if exist ".venv\Scripts\python.exe" goto venv_ok
echo Criando o ambiente Python...
python -m venv .venv
if errorlevel 1 goto erro_python
:venv_ok

echo Instalando as bibliotecas - pode demorar alguns minutos...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 goto erro_pip

".venv\Scripts\python.exe" -m scripts.instalar
if errorlevel 1 goto erro

echo.
echo ==================================================
echo   Instalacao concluida!
echo   Para usar o sistema, de dois cliques no INICIAR.bat
echo ==================================================
goto fim

:erro_python
echo.
echo [ERRO] Nao encontrei o Python 3.12 ou mais novo.
echo Rode ferramentas\preparar_computador\PREPARAR_COMPUTADOR.bat e depois este INSTALAR.bat de novo.
goto fim_erro

:erro_pip
echo.
echo [ERRO] Falha ao instalar as bibliotecas. Verifique a internet e rode o INSTALAR.bat de novo.
goto fim_erro

:erro
echo A instalacao nao terminou. Corrija o problema indicado acima e rode o INSTALAR.bat de novo.
goto fim_erro

:fim_erro
if /i not "%~1"=="/sem-pausa" pause
exit /b 1

:fim
if /i not "%~1"=="/sem-pausa" pause
exit /b 0
