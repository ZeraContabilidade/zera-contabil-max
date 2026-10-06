@echo off
setlocal
cd /d "%~dp0"
title ZERA CONTABIL MAX
if exist ".venv\Scripts\python.exe" goto iniciar
echo O sistema ainda nao foi instalado. De dois cliques no INSTALAR.bat primeiro.
pause
exit /b 1

:iniciar
".venv\Scripts\python.exe" -m scripts.iniciar %*
if errorlevel 1 pause
