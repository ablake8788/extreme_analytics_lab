# build.ps1 - Builds dist\ExtremeAnalyticsLab.exe from the extreme_analytics_lab project.
# Run from the project root (the folder that contains run.py and requirements.txt).

$ErrorActionPreference = "Stop"
$AppName = "ExtremeAnalyticsLab"

Write-Host "== Extreme & Change Analytics Lab - EXE build ==" -ForegroundColor Cyan

# 0a. The .exe always runs in local mode (no login)
if ((Test-Path "config.ini") -and (Select-String -Path "config.ini" -Pattern '^\s*mode\s*=\s*server' -Quiet)) {
    Write-Host "config.ini has mode = server. The .exe must be built with mode = local." -ForegroundColor Red
    Write-Host "Set [app] mode = local in config.ini (use config.local.ini to test the login locally)." -ForegroundColor Red
    exit 1
}

# 0. Sanity checks
foreach ($f in @("run.py", "requirements.txt")) {
    if (-not (Test-Path $f)) {
        Write-Host "Missing $f. Run this script from the extreme_analytics_lab project root." -ForegroundColor Red
        exit 1
    }
}

# 1. Virtual environment (reuse if it exists)
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}
# Keep Dropbox from syncing the venv and build output
foreach ($d in @(".venv", "build", "dist")) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory $d | Out-Null }
    try { Set-Content -Path $d -Stream "com.dropbox.ignored" -Value 1 -ErrorAction Stop } catch { }
}
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# 1b. Health check: a half-deleted venv (e.g. from a Dropbox lock) has a broken pip
& .\.venv\Scripts\python.exe -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Virtual environment is damaged (pip is broken). Recreating it..." -ForegroundColor Yellow
    if (Get-Command deactivate -ErrorAction SilentlyContinue) { deactivate }
    try { Remove-Item -Recurse -Force ".venv" -ErrorAction Stop }
    catch {
        Write-Host "Could not delete .venv - it is locked. Close VS Code/terminals using it, pause Dropbox, and run .\build.ps1 again." -ForegroundColor Red
        exit 1
    }
    python -m venv .venv
    try { Set-Content -Path ".venv" -Stream "com.dropbox.ignored" -Value 1 -ErrorAction Stop } catch { }
    & .\.venv\Scripts\Activate.ps1
}

# 2. Dependencies + build tools (stop on any failure)
Write-Host "Installing dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Host "pip upgrade failed." -ForegroundColor Red; exit 1 }
python -m pip install -r requirements.txt pyinstaller pytest
if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed - see errors above." -ForegroundColor Red; exit 1 }

# 3. Tests must pass before building
if (Test-Path "tests") {
    Write-Host "Running tests..." -ForegroundColor Yellow
    python -m pytest tests\ -v
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nTests failed. Build aborted - fix the errors above first." -ForegroundColor Red
        exit 1
    }
    Write-Host "Tests passed." -ForegroundColor Green
} else {
    Write-Host "No tests folder found - skipping tests." -ForegroundColor Yellow
}

# 3b. Build counter: next build number, stamped into app\static\build_info.json
#     (bundled into the exe and shown in the app's corner badge)
$infoPath = "app\static\build_info.json"
$prevInfo = $null
$lastBuild = 0
if (Test-Path $infoPath) {
    $prevInfo = [IO.File]::ReadAllText((Resolve-Path $infoPath))
    try { $lastBuild = [int](($prevInfo | ConvertFrom-Json).build) } catch { $lastBuild = 0 }
}
$buildNo = $lastBuild + 1
$branch = ""; $commit = ""
try { $branch = (& git rev-parse --abbrev-ref HEAD 2>$null) } catch { }
try { $commit = (& git rev-parse --short HEAD 2>$null) } catch { }
$info = [ordered]@{
    build    = $buildNo
    version  = "1.0.$buildNo"
    built_at = (Get-Date -Format "yyyy-MM-dd HH:mm")
    branch   = "$branch".Trim()
    commit   = "$commit".Trim()
}
if (-not (Test-Path "app\static")) { New-Item -ItemType Directory "app\static" | Out-Null }
[IO.File]::WriteAllText((Join-Path (Get-Location).Path $infoPath), ($info | ConvertTo-Json))
Write-Host "Build number: $buildNo (version $($info.version))" -ForegroundColor Cyan

# 4. Find Flask templates/static folders so they get bundled into the exe
$root = (Get-Location).Path
$excluded = @(".venv", "build", "dist", ".git")
$dataDirs = Get-ChildItem -Recurse -Directory |
    Where-Object { $_.Name -in @("templates", "static") } |
    Where-Object {
        $rel = $_.FullName.Substring($root.Length + 1)
        -not ($excluded | Where-Object { $rel -like "$_*" })
    }

$pyiArgs = @("--noconfirm", "--clean", "--onefile", "--name", $AppName)
foreach ($d in $dataDirs) {
    $rel = $d.FullName.Substring($root.Length + 1)
    Write-Host "Bundling data folder: $rel" -ForegroundColor DarkGray
    $pyiArgs += @("--add-data", "$rel;$rel")
}

# config.ini (default parameters) and matplotlib's image backend for reports
if (Test-Path "config.ini") { $pyiArgs += @("--add-data", "config.ini;.") }
if (Select-String -Path "requirements.txt" -Pattern "matplotlib" -Quiet) {
    $pyiArgs += @("--hidden-import", "matplotlib.backends.backend_agg")
}

# Include the whole app package and the Excel readers
if (Test-Path "app\__init__.py") { $pyiArgs += @("--collect-submodules", "app") }
$pyiArgs += @("--hidden-import", "openpyxl")
$pyiArgs += "run.py"

# 5. Clean old output and build (stop a running copy first so dist\ isn't locked)
Get-Process -Name $AppName -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
foreach ($d in @("build", "dist")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
if (Test-Path "$AppName.spec") { Remove-Item -Force "$AppName.spec" }

Write-Host "Building $AppName.exe (1-3 minutes)..." -ForegroundColor Yellow
pyinstaller @pyiArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path "dist\$AppName.exe")) {
    # Failed build does not use up a build number
    if ($prevInfo) { [IO.File]::WriteAllText((Join-Path (Get-Location).Path $infoPath), $prevInfo) }
    else { Remove-Item $infoPath -ErrorAction SilentlyContinue }
    Write-Host "`nBuild failed. Paste the error above into the chat." -ForegroundColor Red
    exit 1
}

foreach ($d in @("build", "dist")) {
    try { Set-Content -Path $d -Stream "com.dropbox.ignored" -Value 1 -ErrorAction Stop } catch { }
}

$size = [math]::Round((Get-Item "dist\$AppName.exe").Length / 1MB, 1)
Write-Host "`nBuild succeeded! dist\$AppName.exe ($size MB) - build $buildNo" -ForegroundColor Green
Write-Host "Commit app\static\build_info.json so the build number is kept in git." -ForegroundColor DarkGray
Write-Host "Run it with:  .\dist\$AppName.exe" -ForegroundColor Cyan
Write-Host "Then open:    http://127.0.0.1:5100" -ForegroundColor Cyan
