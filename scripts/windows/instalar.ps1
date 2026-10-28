# AUTO SERE - assistente de instalação (Windows)
#
# 1. Pergunta em que pasta instalar (janela do Windows).
# 2. Copia o programa para essa pasta.
# 3. Prepara um Python PRÓPRIO do projeto em <pasta>\runtime\python (versão
#    portátil do python.org: só extrai um zip, sem instalador e sem registro no
#    Windows; não depende do Python do sistema), as bibliotecas e os navegadores.
# 4. Cria o atalho "AUTO SERE" e abre o sistema. Os dados da escola (nome, CEP,
#    endereço) são pedidos pelo assistente que abre dentro do próprio sistema.
#
# Pode ser executado de novo sem problema: se a pasta já tiver o AUTO SERE,
# atualiza o programa e NÃO apaga dados, credenciais nem configurações.
# Requer internet na primeira vez. Não requer administrador.
#
# Uso sem janela:  instalar.ps1 -Destino "C:\AUTO_SERE" -Silencioso
param(
    [string]$Destino = "",
    [switch]$Silencioso
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Titulo($t) { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Falha($t)  { Write-Host ""; Write-Host "ERRO: $t" -ForegroundColor Red; exit 1 }

$origem = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "=============================================="
Write-Host " AUTO SERE - instalação (Windows)"
Write-Host "=============================================="

# Confere se este é mesmo o projeto completo (e não só alguns arquivos soltos).
foreach ($obrigatorio in @("src\comum\paths.py", "src\web\app.py", "requirements.txt")) {
    if (-not (Test-Path (Join-Path $origem $obrigatorio))) {
        Falha "Pacote incompleto: não encontrei '$obrigatorio' em $origem. Extraia o zip COMPLETO do AUTO SERE e rode a instalação de dentro dele."
    }
}

# ---------------------------------------------------------------- validação da pasta

# Devolve uma mensagem de erro, ou "" se a pasta serve.
function Validar-Destino([string]$caminho) {
    $c = ($caminho + "").Trim().TrimEnd('\')
    if (-not $c) { return "Informe a pasta de instalação." }
    if ($c -notmatch '^[A-Za-z]:\\.+') {
        return "Informe um caminho completo de um disco local, por exemplo: C:\AUTO_SERE"
    }
    try {
        $di = New-Object System.IO.DriveInfo ($c.Substring(0, 1))
        if (-not $di.IsReady) { return "O disco $($c.Substring(0, 2)) não está pronto ou não existe." }
        if ($di.DriveType -eq [System.IO.DriveType]::Network) {
            return "O disco $($c.Substring(0, 2)) é uma unidade de rede. Instale num disco local (ex.: C:\AUTO_SERE); os DADOS podem continuar na rede."
        }
        if ($di.DriveType -eq [System.IO.DriveType]::Removable) {
            return "O disco $($c.Substring(0, 2)) é removível. Instale num disco fixo do computador."
        }
    } catch { return "Não foi possível verificar o disco informado." }
    foreach ($protegida in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:SystemRoot)) {
        if ($protegida -and $c.StartsWith($protegida, [System.StringComparison]::OrdinalIgnoreCase)) {
            return "Essa pasta exige permissão de administrador. Escolha outra (ex.: C:\AUTO_SERE)."
        }
    }
    $mesma = ($c -ieq $origem.TrimEnd('\'))
    if ((Test-Path $c) -and -not $mesma) {
        $jaInstalado = Test-Path (Join-Path $c "src")
        $temItens = @(Get-ChildItem -LiteralPath $c -Force -ErrorAction SilentlyContinue).Count -gt 0
        if ($temItens -and -not $jaInstalado) {
            return "A pasta não está vazia e não contém uma instalação do AUTO SERE. Escolha uma pasta nova ou vazia."
        }
    }
    try {
        New-Item -ItemType Directory -Force -Path $c | Out-Null
        $teste = Join-Path $c ".teste-escrita"
        Set-Content -LiteralPath $teste -Value "ok"
        Remove-Item -LiteralPath $teste -Force
    } catch { return "Não consigo gravar nessa pasta: $($_.Exception.Message)" }
    return ""
}

# ---------------------------------------------------------------- janela de escolha

function Escolher-Destino([string]$padrao) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        [System.Windows.Forms.Application]::EnableVisualStyles()
    } catch {
        $r = Read-Host "Pasta de instalação [$padrao]"
        if ($r) { return $r.Trim() } else { return $padrao }
    }
    $fonte = "Segoe UI"
    $f = New-Object System.Windows.Forms.Form
    $f.Text = "AUTO SERE - Instalação"
    $f.StartPosition = "CenterScreen"
    $f.FormBorderStyle = "FixedDialog"
    $f.MaximizeBox = $false
    $f.MinimizeBox = $false
    $f.ClientSize = New-Object System.Drawing.Size(580, 260)
    $f.Font = New-Object System.Drawing.Font($fonte, 9)

    $titulo = New-Object System.Windows.Forms.Label
    $titulo.Text = "Bem-vindo ao AUTO SERE"
    $titulo.Font = New-Object System.Drawing.Font($fonte, 15, [System.Drawing.FontStyle]::Bold)
    $titulo.Location = New-Object System.Drawing.Point(20, 16)
    $titulo.AutoSize = $true

    $info = New-Object System.Windows.Forms.Label
    $info.Text = "Escolha a pasta onde o AUTO SERE será instalado. O programa, o Python e os navegadores ficam todos dentro dela. Depois da instalação, o próprio sistema pergunta os dados da escola (nome, CEP e endereço)."
    $info.Location = New-Object System.Drawing.Point(20, 56)
    $info.Size = New-Object System.Drawing.Size(540, 52)

    $rotulo = New-Object System.Windows.Forms.Label
    $rotulo.Text = "Pasta de instalação:"
    $rotulo.Location = New-Object System.Drawing.Point(20, 116)
    $rotulo.AutoSize = $true

    $caixa = New-Object System.Windows.Forms.TextBox
    $caixa.Text = $padrao
    $caixa.Location = New-Object System.Drawing.Point(20, 138)
    $caixa.Size = New-Object System.Drawing.Size(430, 24)

    $procurar = New-Object System.Windows.Forms.Button
    $procurar.Text = "Procurar..."
    $procurar.Location = New-Object System.Drawing.Point(460, 136)
    $procurar.Size = New-Object System.Drawing.Size(100, 28)

    $dica = New-Object System.Windows.Forms.Label
    $dica.Text = "Use um disco local (ex.: C:\AUTO_SERE). Evite unidades de rede e a pasta Arquivos de Programas."
    $dica.ForeColor = [System.Drawing.Color]::DimGray
    $dica.Location = New-Object System.Drawing.Point(20, 170)
    $dica.Size = New-Object System.Drawing.Size(540, 36)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "Instalar"
    $ok.Location = New-Object System.Drawing.Point(350, 212)
    $ok.Size = New-Object System.Drawing.Size(100, 32)
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK

    $cancelar = New-Object System.Windows.Forms.Button
    $cancelar.Text = "Cancelar"
    $cancelar.Location = New-Object System.Drawing.Point(460, 212)
    $cancelar.Size = New-Object System.Drawing.Size(100, 32)
    $cancelar.DialogResult = [System.Windows.Forms.DialogResult]::Cancel

    $procurar.Add_Click({
        $d = New-Object System.Windows.Forms.FolderBrowserDialog
        $d.Description = "Escolha a pasta de instalação do AUTO SERE"
        $d.ShowNewFolderButton = $true
        if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $sel = $d.SelectedPath.TrimEnd('\')
            $itens = @(Get-ChildItem -LiteralPath $sel -Force -ErrorAction SilentlyContinue).Count
            # Pasta com conteúdo (e que não é uma instalação): instala numa subpasta nova.
            if ($itens -gt 0 -and -not (Test-Path (Join-Path $sel "src"))) { $sel = Join-Path $sel "AUTO_SERE" }
            $caixa.Text = $sel
        }
    })

    $f.Controls.AddRange(@($titulo, $info, $rotulo, $caixa, $procurar, $dica, $ok, $cancelar))
    $f.AcceptButton = $ok
    $f.CancelButton = $cancelar

    while ($true) {
        $resultado = $f.ShowDialog()
        if ($resultado -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
        $erro = Validar-Destino $caixa.Text
        if (-not $erro) { return $caixa.Text.Trim().TrimEnd('\') }
        [System.Windows.Forms.MessageBox]::Show($erro, "AUTO SERE", "OK", "Warning") | Out-Null
    }
}

# ---------------------------------------------------------------- escolha do destino

if ($Destino) {
    $erro = Validar-Destino $Destino
    if ($erro) { Falha $erro }
    $raiz = $Destino.Trim().TrimEnd('\')
} else {
    # Se já estamos rodando de dentro de uma instalação, o padrão é reparar ela mesma.
    if (Test-Path (Join-Path $origem "runtime\python\python.exe")) { $padrao = $origem } else { $padrao = "C:\AUTO_SERE" }
    $raiz = Escolher-Destino $padrao
    if (-not $raiz) { Write-Host "Instalação cancelada."; exit 2 }
}
Write-Host "Pasta de instalação: $raiz"

$runtime    = Join-Path $raiz "runtime"
$pyDir      = Join-Path $runtime "python"
$pyExe      = Join-Path $pyDir "python.exe"
$navegs     = Join-Path $runtime "browsers"
$zipPy      = Join-Path $runtime "python-embed.zip"
$getPip     = Join-Path $runtime "get-pip.py"

# Python local válido = existe, versão >= 3.10 e tem ssl, sqlite3, ctypes e pip.
function Python-Ok($exe) {
    if (-not (Test-Path $exe)) { return $false }
    try {
        & $exe -c "import sys, ssl, sqlite3, ctypes, pip; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# Baixa um arquivo e confere se o tamanho é plausível (evita arquivo pela metade).
function Baixar($url, $arquivo, $minimoBytes) {
    Invoke-WebRequest -Uri $url -OutFile $arquivo -UseBasicParsing
    if ((Get-Item -LiteralPath $arquivo).Length -lt $minimoBytes) {
        Remove-Item -LiteralPath $arquivo -Force
        throw "arquivo baixado incompleto"
    }
}

# ---------------------------------------------------------------- 1. copiar o programa

if ($origem.TrimEnd('\') -ine $raiz) {
    Titulo "[1/6] Copiando o programa para $raiz ..."
    $atualizando = Test-Path (Join-Path $raiz "src")
    $excluirPastas = @("runtime", "__pycache__", ".git", ".venv")
    $excluirArquivos = @()
    if ($atualizando) {
        Write-Host "Instalação existente encontrada: atualizando o programa e preservando dados, credenciais e configurações."
        $excluirPastas += @("dados", "credenciais")
        $excluirArquivos += "config_usuario.json"
    }
    $opcoesCopia = @($origem, $raiz, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD") + $excluirPastas
    if ($excluirArquivos.Count -gt 0) { $opcoesCopia += "/XF"; $opcoesCopia += $excluirArquivos }
    & robocopy @opcoesCopia | Out-Null
    if ($LASTEXITCODE -ge 8) { Falha "Falha ao copiar os arquivos (robocopy código $LASTEXITCODE)." }
} else {
    Titulo "[1/6] Instalando na própria pasta do pacote."
}
Set-Location $raiz

# ---------------------------------------------------------------- 2. Python próprio

# Usa o Python "embutível" do python.org: um zip que só é extraído (sem instalador,
# sem registro no Windows, sem administrador) e que já traz junto as DLLs de runtime
# do Visual C++. Funciona igual com ou sem Python instalado no computador, e um
# Python quebrado do sistema não atrapalha.
if (Python-Ok $pyExe) {
    Titulo "[2/6] Python local já pronto em runtime\python."
} else {
    Titulo "[2/6] Preparando Python local em runtime\python ..."
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    if (Test-Path $pyDir) { Remove-Item -Recurse -Force $pyDir }   # restos de tentativa anterior

    if (-not (Test-Path $zipPy)) {
        $versoes = @("3.12.10", "3.12.9", "3.12.8", "3.11.9")
        $baixou = $false
        foreach ($v in $versoes) {
            $url = "https://www.python.org/ftp/python/$v/python-$v-embed-amd64.zip"
            Write-Host "Baixando Python $v (versão portátil) ..."
            try { Baixar $url $zipPy 5MB; $baixou = $true; break }
            catch { Write-Host "  não foi possível baixar $v ($($_.Exception.Message))" }
        }
        if (-not $baixou) {
            Falha "Não foi possível baixar o Python. Sem internet? Baixe o 'Windows embeddable package (64-bit)' 3.12 em python.org/downloads/windows e salve como runtime\python-embed.zip, depois rode de novo."
        }
    } else {
        Write-Host "Usando runtime\python-embed.zip (já existente)."
    }

    Expand-Archive -LiteralPath $zipPy -DestinationPath $pyDir -Force

    # O embutível vem "trancado": só enxerga a própria pasta. Liberamos o site-packages
    # (para o pip) e a raiz do projeto (..\.. a partir de runtime\python), para o
    # "import src..." funcionar de qualquer lugar.
    $pth = Get-ChildItem -LiteralPath $pyDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) { Falha "Arquivo ._pth não encontrado no Python portátil." }
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($pth.Name)
    [System.IO.File]::WriteAllLines($pth.FullName, @("$stem.zip", ".", "Lib\site-packages", "..\..", "import site"), (New-Object System.Text.UTF8Encoding $false))

    if (-not (Test-Path $getPip)) {
        try { Baixar "https://bootstrap.pypa.io/get-pip.py" $getPip 1KB }
        catch { Falha "Não foi possível baixar o instalador do pip ($($_.Exception.Message))." }
    }
    & $pyExe $getPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { Falha "Falha ao instalar o pip no Python portátil." }
    if (-not (Python-Ok $pyExe)) { Falha "O Python portátil não passou na verificação (ssl, sqlite3, ctypes, pip)." }
    Write-Host "Python portátil pronto."
}

# ---------------------------------------------------------------- 3. bibliotecas

Titulo "[3/6] Instalando bibliotecas (pode levar alguns minutos) ..."
& $pyExe -m pip install --upgrade pip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { Falha "Não foi possível atualizar o pip." }
& $pyExe -m pip install -r (Join-Path $raiz "requirements.txt") --no-warn-script-location
if ($LASTEXITCODE -ne 0) { Falha "Falha ao instalar as bibliotecas do requirements.txt." }

# ---------------------------------------------------------------- 4. navegadores

Titulo "[4/6] Instalando navegadores do Playwright (chromium e firefox) ..."
$env:PLAYWRIGHT_BROWSERS_PATH = $navegs
& $pyExe -m playwright install chromium firefox
if ($LASTEXITCODE -ne 0) { Falha "Falha ao instalar os navegadores do Playwright." }

# ---------------------------------------------------------------- 5. pastas de trabalho

Titulo "[5/6] Criando pastas de trabalho ..."
& $pyExe -c "from src.comum import paths; paths.garantir_diretorios_runtime()"
if ($LASTEXITCODE -ne 0) { Falha "Falha ao criar as pastas de trabalho." }

# ---------------------------------------------------------------- 6. atalho e abertura

Titulo "[6/6] Criando atalho AUTO SERE ..."
& (Join-Path $raiz "scripts\windows\criar_atalho.ps1")

Write-Host ""
Write-Host "Instalação concluída em: $raiz" -ForegroundColor Green
Write-Host "Use o atalho AUTO SERE na área de trabalho ou no menu Iniciar."
if (-not $Silencioso) {
    Write-Host "Abrindo o AUTO SERE: preencha os dados da escola quando o assistente aparecer."
    Start-Process -FilePath (Join-Path $pyDir "pythonw.exe") -ArgumentList @("-m", "src.launcher") -WorkingDirectory $raiz
}
