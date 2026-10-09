@echo off
setlocal
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
cd /d "%RAIZ%\sistema"
title ZERA CONTABIL MAX - Restaurar backup
if exist "%RAIZ%\.venv\Scripts\python.exe" goto rodar
echo O sistema ainda nao foi instalado. Nesta pasta Ferramentas, de dois cliques no INSTALAR.bat.
pause
exit /b 1

:rodar
"%RAIZ%\.venv\Scripts\python.exe" -m scripts.restaurar %*
pause
