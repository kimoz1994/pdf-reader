# run.ps1 — launch the app once using the pdf-reader-clean env python.
# Must run from gui_app/ (main.py uses flat imports), so we cd there.
$ErrorActionPreference = "Stop"

$envName = "pdf-reader-clean"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$guiDir = Join-Path $repoRoot "pdf_reader\gui_app"

# Resolve the env python.
$condaPrefix = "D:\volume\tempprograms\anaconda\envs\$envName"
$python = Join-Path $condaPrefix "python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Env python not found: $python"
}

Push-Location $guiDir
try {
    & $python main.py
}
finally {
    Pop-Location
}