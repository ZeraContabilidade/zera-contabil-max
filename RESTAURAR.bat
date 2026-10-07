@echo off
setlocal
cd /d "%~dp0"
title ZERA CONTABIL MAX - Restaurar backup
if exist ".venv\Scripts\python.exe" goto restaurar
echo O sistema ainda nao foi instalado. De dois cliques no INSTALAR.bat primeiro.
pause
exit /b 1

:restaurar
".venv\Scripts\python.exe" -m scripts.restaurar %*
pause
