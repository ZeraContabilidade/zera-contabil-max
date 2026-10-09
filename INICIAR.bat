@echo off
setlocal
cd /d "%~dp0sistema"
title ZERA CONTABIL MAX
if exist "%~dp0.venv\Scripts\python.exe" goto iniciar
echo O sistema ainda nao foi instalado.
echo Abra a pasta Ferramentas e de dois cliques no INSTALAR.bat.
pause
exit /b 1

:iniciar
"%~dp0.venv\Scripts\python.exe" -m scripts.iniciar %*
if errorlevel 1 pause
