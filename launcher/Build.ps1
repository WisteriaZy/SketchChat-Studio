$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) {
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
& $csc /nologo /target:winexe /platform:anycpu /reference:System.Windows.Forms.dll "/out:$root\StartStudio.exe" "$PSScriptRoot\StudioLauncher.cs"
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed' }
