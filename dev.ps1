# dev.ps1 — run the app and auto-restart it whenever a .py file under gui_app changes.
# Press Ctrl+C to stop the watcher.
$ErrorActionPreference = "Stop"

$envName = "pdf-reader-clean"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$guiDir = Join-Path $repoRoot "pdf_reader\gui_app"
$python = "D:\volume\tempprograms\anaconda\envs\$envName\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Env python not found: $python"
}

# Snapshot of file mtimes that live behind the running process.
$getState = {
    Get-ChildItem -Path $guiDir -Recurse -Filter *.py | ForEach-Object {
        [PSCustomObject]@{ Path = $_.FullName; Time = $_.LastWriteTimeUtc }
    }
}

$state = & $getState
$proc = $null

function Start-App {
    param([System.Diagnostics.Process]$Current)
    if ($Current -and -not $Current.HasExited) {
        $Current.CloseMainWindow() | Out-Null
        $Current.WaitForExit(2000) | Out-Null
        if (-not $Current.HasExited) { $Current.Kill() }
    }
    New-Item -ItemType Directory -Path $guiDir -Force | Out-Null
    $proc = Start-Process -FilePath $python -ArgumentList "main.py" `
        -WorkingDirectory $guiDir -PassThru
    Write-Host "[dev] app started (PID $($proc.Id))" -ForegroundColor Green
    return $proc
}

Write-Host "[dev] watching $guiDir for *.py changes. Ctrl+C to quit." -ForegroundColor Cyan
$proc = Start-App -Current $null

try {
    while ($true) {
        Start-Sleep -Milliseconds 800
        $newState = & $getState
        $changed = $false
        foreach ($f in $newState) {
            $old = $state | Where-Object { $_.Path -eq $f.Path }
            if (-not $old -or $old.Time -ne $f.Time) { $changed = $true; break }
        }
        if ($changed) {
            Write-Host "[dev] change detected, restarting..." -ForegroundColor Yellow
            $proc = Start-App -Current $proc
            $state = & $getState
        }
    }
}
finally {
    if ($proc -and -not $proc.HasExited) {
        $proc.CloseMainWindow() | Out-Null
        $proc.WaitForExit(2000) | Out-Null
        if (-not $proc.HasExited) { $proc.Kill() }
    }
}