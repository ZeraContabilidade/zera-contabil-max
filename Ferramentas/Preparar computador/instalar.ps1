# ============================================================
#  ZERA CONTABIL MAX - Instalador completo desta maquina
#  Parte 1 (administrador, vale para o computador todo):
#     Git, Python 3.12, Node.js LTS, GitHub CLI, WSL2, Docker Desktop
#  Parte 2 (usuario atual):
#     Claude Code + extensoes Playwright e Context7
#  Execute pelo PREPARAR_COMPUTADOR.bat (fica em Ferramentas\Preparar computador)
# ============================================================
param([switch]$Admin)

$ErrorActionPreference = "Continue"
$Pasta = Split-Path -Parent $MyInvocation.MyCommand.Path      # Ferramentas\Preparar computador
$Log = Join-Path $Pasta "instalacao_log.txt"

function Titulo($t) { Write-Host ""; Write-Host "==== $t ====" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "  [OK] $t" -ForegroundColor Green }
function Aviso($t)  { Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Erro($t)   { Write-Host "  [X]  $t" -ForegroundColor Red }
function Atualizar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User") + ";" +
                "$env:USERPROFILE\.local\bin"
}
function Tem($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Instalar-Pacote($id, $nome, $extra) {
    Titulo $nome
    $a = @("install","--id",$id,"-e","--silent","--scope","machine",
              "--accept-source-agreements","--accept-package-agreements")
    if ($extra) { $a += $extra }
    & winget.exe @a
    if ($LASTEXITCODE -eq 0) { Ok "$nome instalado." }
    else {
        # alguns pacotes nao aceitam --scope machine: tenta sem
        $a = $a | Where-Object { $_ -ne "--scope" -and $_ -ne "machine" }
        & winget.exe @a
        if ($LASTEXITCODE -eq 0) { Ok "$nome instalado." }
        else { Aviso "$nome retornou codigo $LASTEXITCODE (pode ja estar instalado)." }
    }
    Atualizar-Path
}

# ============================================================
#  PARTE 1 - ADMINISTRADOR
# ============================================================
if ($Admin) {
    Start-Transcript -Path (Join-Path $Pasta "instalacao_admin_log.txt") -Append | Out-Null
    Titulo "PARTE 1 - Programas (administrador)"
    if (-not (Tem "winget.exe")) {
        Erro "O 'winget' nao foi encontrado. Atualize o 'Instalador de Aplicativo' pela Microsoft Store e rode de novo."
        Read-Host "Enter para fechar"; exit 1
    }

    if (Tem "git") { Ok "Git ja instalado." } else { Instalar-Pacote "Git.Git" "Git for Windows" $null }

    $pyOk = $false
    try { $v = & python --version 2>$null; if ($v -match "Python 3") { $pyOk = $true } } catch { }
    if ($pyOk) { Ok "Python ja instalado ($v)." }
    else { Instalar-Pacote "Python.Python.3.12" "Python 3.12" @("--override","/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0") }

    if (Tem "node") { Ok "Node.js ja instalado." } else { Instalar-Pacote "OpenJS.NodeJS.LTS" "Node.js LTS" $null }
    if (Tem "gh")   { Ok "GitHub CLI ja instalado." } else { Instalar-Pacote "GitHub.cli" "GitHub CLI" $null }

    Titulo "WSL2 (base do Docker)"
    wsl --status *> $null
    if ($LASTEXITCODE -ne 0) { wsl --install --no-distribution; Aviso "WSL2 instalado - REINICIE o computador ao final." }
    else { Ok "WSL2 ja disponivel." }

    Titulo "Docker Desktop"
    if (Test-Path "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe") { Ok "Docker Desktop ja instalado." }
    else {
        winget.exe install --id Docker.DockerDesktop -e --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) { Ok "Docker Desktop instalado - REINICIE o computador ao final." }
        else { Aviso "Docker retornou codigo $LASTEXITCODE. Se falhar, baixe em docker.com/products/docker-desktop" }
    }
    # coloca o usuario que esta usando o computador no grupo docker-users
    try {
        $logado = (Get-CimInstance Win32_ComputerSystem).UserName
        if ($logado) { Add-LocalGroupMember -Group "docker-users" -Member $logado -ErrorAction Stop; Ok "$logado adicionado ao grupo docker-users." }
    } catch { Ok "Usuario ja esta no grupo docker-users (ou grupo sera criado apos reiniciar)." }

    Ok "Parte 1 concluida. Esta janela vai fechar e a Parte 2 continua."
    Stop-Transcript | Out-Null
    Start-Sleep -Seconds 3
    exit 0
}

# ============================================================
#  PARTE 2 - USUARIO ATUAL
# ============================================================
Start-Transcript -Path $Log -Append | Out-Null
Titulo "Instalador ZERA CONTABIL MAX - usuario: $env:USERNAME"
Write-Host "Vai abrir uma janela pedindo permissao de administrador. Clique em SIM." -ForegroundColor Yellow
Write-Host "Aguarde a janela azul de administrador terminar..." -ForegroundColor Yellow
try {
    $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Admin"
    Ok "Parte 1 (programas) finalizada."
} catch {
    Erro "A permissao de administrador foi negada. Os programas da Parte 1 nao foram instalados."
}

Atualizar-Path
Titulo "PARTE 2 - Claude Code para o usuario $env:USERNAME"
if (Tem "claude") { Ok "Claude Code ja instalado." }
else {
    try {
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        $userPath = [Environment]::GetEnvironmentVariable("Path","User")
        if ($userPath -notlike "*\.local\bin*") {
            [Environment]::SetEnvironmentVariable("Path", "$userPath;$env:USERPROFILE\.local\bin", "User")
        }
        Atualizar-Path
        Ok "Claude Code instalado."
    } catch { Erro "Falha ao instalar o Claude Code: $_" }
}

Titulo "Extensoes do Claude Code (MCP)"
Atualizar-Path
if ((Tem "claude") -and (Tem "npx")) {
    $lista = (claude mcp list 2>$null) | Out-String
    if ($lista -notmatch "playwright") { claude mcp add -s user playwright -- cmd /c npx -y "@playwright/mcp@latest"; Ok "Playwright adicionado." } else { Ok "Playwright ja configurado." }
    if ($lista -notmatch "context7")   { claude mcp add -s user context7 -- cmd /c npx -y "@upstash/context7-mcp"; Ok "Context7 adicionado." } else { Ok "Context7 ja configurado." }
} else {
    Aviso "Claude Code ou Node.js ainda nao reconhecidos nesta janela. REINICIE o computador e rode o PREPARAR_COMPUTADOR.bat de novo (ele pula o que ja estiver instalado)."
}

Titulo "Resumo"
foreach ($c in @("git","python","node","npm","gh","claude","docker")) {
    if (Tem $c) { Ok "$c encontrado" } else { Aviso "$c ainda nao encontrado (reinicie o computador)" }
}
Write-Host ""
Write-Host "PROXIMOS PASSOS:" -ForegroundColor Cyan
Write-Host " 1. REINICIE o computador." -ForegroundColor Cyan
Write-Host " 2. Abra o Docker Desktop uma vez e aceite os termos." -ForegroundColor Cyan
Write-Host " 3. Rode o VERIFICAR.bat e confira o arquivo verificacao.txt." -ForegroundColor Cyan
Write-Host " 4. Na pasta Ferramentas, de dois cliques no INSTALAR.bat (instala o sistema)." -ForegroundColor Cyan
Write-Host "Log em: $Log"
Stop-Transcript | Out-Null
Read-Host "Pressione Enter para fechar"
