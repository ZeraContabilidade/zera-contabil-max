@echo off
setlocal
cd /d "%~dp0"
title ZERA CONTABIL MAX - Fechar acesso pela rede
if exist ".venv\Scripts\python.exe" goto rede
echo O sistema ainda nao foi instalado. De dois cliques no INSTALAR.bat primeiro.
pause
exit /b 1

:rede
".venv\Scripts\python.exe" -m scripts.rede fechar
pause
