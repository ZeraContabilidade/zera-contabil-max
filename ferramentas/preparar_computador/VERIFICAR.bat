@echo off
cd /d "%~dp0"
echo Verificando o ambiente... aguarde.
(
echo ==== VERIFICACAO %date% %time% ====
echo --- python ---
python --version 2>&1
where python 2>&1
echo --- git ---
git --version 2>&1
echo --- node / npm ---
node --version 2>&1
call npm --version 2>&1
echo --- gh ---
gh --version 2>&1
echo --- claude ---
call claude --version 2>&1
echo --- wsl ---
wsl --status 2>&1
echo --- docker ---
docker --version 2>&1
docker info --format "Docker rodando: {{.ServerVersion}}" 2>&1
echo --- extensoes MCP ---
call claude mcp list 2>&1
echo ==== FIM ====
) > verificacao.txt 2>&1
echo.
echo Pronto! Resultado salvo em verificacao.txt
pause
