# launch.ps1 - Starts dist\ExtremeAnalyticsLab.exe and opens it in the browser.
# Run from the extreme_analytics_lab project root after build.ps1 has succeeded.

$ErrorActionPreference = "Stop"
$AppName = "ExtremeAnalyticsLab"
$Exe = "dist\$AppName.exe"
$Url = "http://127.0.0.1:5100"

Write-Host "== Extreme & Change Analytics Lab - launch ==" -ForegroundColor Cyan

if (-not (Test-Path $Exe)) {
    Write-Host "$Exe not found. Run .\build.ps1 first." -ForegroundColor Red
    exit 1
}

# Stop an older copy that may still be running on the same port
$running = Get-Process -Name $AppName -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "Stopping previous instance..." -ForegroundColor Yellow
    $running | Stop-Process -Force
    Start-Sleep -Seconds 1
}

$infoPath = "app\static\build_info.json"
if (Test-Path $infoPath) {
    try {
        $bi = Get-Content $infoPath -Raw | ConvertFrom-Json
        Write-Host "Build $($bi.build) (version $($bi.version), built $($bi.built_at))" -ForegroundColor Cyan
    } catch { }
}
Write-Host "Starting $Exe ..." -ForegroundColor Yellow
Start-Process -FilePath (Resolve-Path $Exe)

# Wait for the server to answer (up to ~30 seconds), then open the browser
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch { }
}

if ($ready) {
    Write-Host "App is running: $Url" -ForegroundColor Green
    Start-Process $Url
} else {
    Write-Host "App did not respond at $Url. Check the app window for an error." -ForegroundColor Red
    exit 1
}

Write-Host "To stop it, close the app window or run: Stop-Process -Name $AppName" -ForegroundColor Cyan
