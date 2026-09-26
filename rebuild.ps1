# rebuild.ps1 - Clean rebuild of the dev environment, then runs the app from source.
# Run from the extreme_analytics_lab project root (the folder that contains run.py).

$ErrorActionPreference = "Stop"

Write-Host "== Extreme & Change Analytics Lab - rebuild ==" -ForegroundColor Cyan

foreach ($f in @("run.py", "requirements.txt")) {
    if (-not (Test-Path $f)) {
        Write-Host "Missing $f. Run this script from the extreme_analytics_lab project root." -ForegroundColor Red
        exit 1
    }
}

# 1. Leave any active venv, stop processes using it, and delete it
if (Get-Command deactivate -ErrorAction SilentlyContinue) { deactivate }

$venvPath = Join-Path (Get-Location).Path ".venv"

# Stop the built exe and any python.exe running from this project's .venv
Get-Process -Name "ExtremeAnalyticsLab" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "python", "pythonw" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($venvPath, [System.StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object {
        Write-Host "Stopping python process $($_.Id) that is using .venv..." -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force
    }

if (Test-Path ".venv") {
    Write-Host "Removing old virtual environment..." -ForegroundColor Yellow
    $removed = $false
    for ($try = 1; $try -le 3 -and -not $removed; $try++) {
        try {
            Remove-Item -Recurse -Force ".venv" -ErrorAction Stop
            $removed = $true
        } catch {
            Write-Host "  .venv is locked (attempt $try of 3), retrying..." -ForegroundColor DarkYellow
            Start-Sleep -Seconds 3
        }
    }
    if (-not $removed) {
        # Still locked (usually Dropbox syncing): move it aside and continue
        $stale = ".venv_old_" + (Get-Date -Format "yyyyMMdd_HHmmss")
        try {
            Rename-Item ".venv" $stale -ErrorAction Stop
            Write-Host "  Could not delete .venv; renamed it to $stale. Delete it later." -ForegroundColor DarkYellow
        } catch {
            Write-Host "`n.venv is locked by another program and cannot be removed or renamed." -ForegroundColor Red
            Write-Host "Close VS Code / terminals using it, pause Dropbox syncing, then run .\rebuild.ps1 again." -ForegroundColor Red
            exit 1
        }
    }
}

# Remove leftover renamed venvs from earlier runs (ignore if still locked)
Get-ChildItem -Directory -Filter ".venv_old_*" -Force -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }

# 2. Clear caches
Get-ChildItem -Recurse -Directory -Include "__pycache__", ".pytest_cache" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "*\.venv\*" } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 3. Fresh venv
Write-Host "Creating virtual environment..." -ForegroundColor Yellow
python -m venv .venv

# Tell Dropbox not to sync .venv (prevents file locks and wasted upload)
try { Set-Content -Path ".venv" -Stream "com.dropbox.ignored" -Value 1 -ErrorAction Stop }
catch { Write-Host "  (Could not mark .venv as Dropbox-ignored; continuing.)" -ForegroundColor DarkGray }

& .\.venv\Scripts\Activate.ps1

# 4. Dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Host "pip upgrade failed." -ForegroundColor Red; exit 1 }
python -m pip install -r requirements.txt pytest
if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed - see errors above." -ForegroundColor Red; exit 1 }

# 5. Tests
if (Test-Path "tests") {
    Write-Host "Running tests..." -ForegroundColor Yellow
    python -m pytest tests\ -v
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nTests failed. Fix the errors above before running the app." -ForegroundColor Red
        exit 1
    }
    Write-Host "Tests passed." -ForegroundColor Green
}

# 6. Run
Write-Host "`nStarting app at http://127.0.0.1:5100  (Ctrl+C to stop)" -ForegroundColor Cyan
python run.py
