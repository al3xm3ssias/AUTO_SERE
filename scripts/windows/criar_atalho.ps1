# Cria o atalho "AUTO SERE" na area de trabalho e no menu Iniciar.
# O atalho aponta direto para pythonw.exe (sem janela de console).
$ErrorActionPreference = "Stop"
$raiz    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonw = Join-Path $raiz "runtime\python\pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe" }
$icone   = Join-Path $raiz "src\web\static\img\auto-sere.ico"

if (-not (Test-Path $pythonw)) {
    Write-Host "ERRO: ambiente nao encontrado. Rode INSTALAR_WINDOWS.bat." -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$destinos = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
)
foreach ($pasta in $destinos) {
    $atalho = $shell.CreateShortcut((Join-Path $pasta "AUTO SERE.lnk"))
    $atalho.TargetPath       = $pythonw
    $atalho.Arguments        = "-m src.launcher"
    $atalho.WorkingDirectory = $raiz
    $atalho.IconLocation     = $icone
    $atalho.Description      = "AUTO SERE - automacoes do portal SERE"
    $atalho.Save()
    Write-Host "Atalho criado em: $pasta"
}
