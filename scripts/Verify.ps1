param([switch]$BuildLauncher)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and install requirements.txt first.' }
Push-Location $root
try {
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    & $python -m compileall -q desktop.py sketchbook tests
    if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed' }
    if ($BuildLauncher) {
        & (Join-Path $root 'launcher\Build.ps1')
        $process = Start-Process -FilePath (Join-Path $root 'StartStudio.exe') -ArgumentList '--verify-launch' -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw 'Console-free launcher verification failed' }
    }
    Write-Output 'Verification passed. No real chat messages were sent.'
} finally { Pop-Location }
