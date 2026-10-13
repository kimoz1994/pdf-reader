# build.ps1 — one-command standalone build (PyInstaller) + smoke check.
# Mirrors run.ps1/dev.ps1: uses the pdf-reader-clean env, runs from the repo
# root (the spec lives here).
#
#   .\build.ps1            build + smoke-check the exe
#   .\build.ps1 -NoCheck   build only
#
# Output: dist/pdf_reader/pdf_reader.exe  (distribute the whole folder)
param(
    [switch]$NoCheck
)
$ErrorActionPreference = "Stop"

$envName = "pdf-reader-clean"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$condaPrefix = "D:\volume\tempprograms\anaconda\envs\$envName"
$python = Join-Path $condaPrefix "python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Env python not found: $python"
}

$spec = Join-Path $repoRoot "pdf_reader.spec"
if (-not (Test-Path $spec)) {
    Write-Error "Spec not found: $spec"
}

Write-Host "[build] PyInstaller -> dist\pdf_reader\pdf_reader.exe" -ForegroundColor Cyan
Push-Location $repoRoot
try {
    & $python -m PyInstaller --noconfirm $spec
    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $exe = Join-Path $repoRoot "dist\pdf_reader\pdf_reader.exe"
    if (-not (Test-Path $exe)) {
        Write-Error "Build reported success but exe is missing: $exe"
    }

    if ($NoCheck) {
        Write-Host "[build] done (no smoke check): $exe" -ForegroundColor Green
        return
    }

    # Smoke check: launch the windowed exe and confirm it stays alive briefly.
    # A crash-on-start (missing Qt plugin / sqlite DLL) shows up as an early exit.
    Write-Host "[build] smoke-check: launching exe for 4s..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $exe -PassThru `
        -WorkingDirectory (Split-Path -Parent $exe)
    Start-Sleep -Seconds 4
    if ($proc.HasExited) {
        $code = $proc.ExitCode
        Write-Error "Smoke check FAILED: exe exited early (exit code $code). Likely a missing bundled plugin or DLL."
    }
    Write-Host "[build] smoke check OK (still running after 4s)" -ForegroundColor Green
    # Graceful close; kill only if it ignores the close request.
    $proc.CloseMainWindow() | Out-Null
    if (-not $proc.WaitForExit(3000)) { $proc.Kill() }

    Write-Host "[build] done: $exe" -ForegroundColor Green
    Write-Host "[build] distribute the WHOLE dist\pdf_reader\ folder (the exe is not self-contained)." -ForegroundColor DarkGray
}
finally {
    Pop-Location
}
