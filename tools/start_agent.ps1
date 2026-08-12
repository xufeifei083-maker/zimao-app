$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$logRoot = Join-Path $env:LOCALAPPDATA "FlynotesAI\logs"
$stdoutPath = Join-Path $logRoot "agent-stdout.log"
$stderrPath = Join-Path $logRoot "agent-stderr.log"

New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList "-m", "flynotes_agent" `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Write-Output $process.Id
