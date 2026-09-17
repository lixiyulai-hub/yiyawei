param(
    [switch]$Hidden,
    [switch]$NoOllama
)

$ErrorActionPreference = "Stop"

$scriptArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Hidden")
if ($NoOllama) {
    $scriptArgs += "-NoOllama"
}
if (-not $Hidden) {
    Start-Process -FilePath "powershell.exe" -ArgumentList $scriptArgs -WindowStyle Hidden
    exit
}

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$OllamaExe = $null

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}

if (-not $NoOllama) {
    $online = $false
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 | Out-Null
        $online = $true
    } catch {
        $online = $false
    }

    if (-not $online) {
        $cmd = Get-Command ollama -ErrorAction SilentlyContinue
        if ($cmd) {
            $OllamaExe = $cmd.Source
        } else {
            throw "Ollama not found in PATH. Install Ollama first or use -NoOllama."
        }

        Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
}

Set-Location $ProjectRoot
& $Python "app.py" "--gui"
