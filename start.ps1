# start.ps1 - start the Extreme & Change Analytics Lab from source.
#
#   .\start.ps1            normal mode, no login
#   .\start.ps1 -Secure    with login (server mode)
#
# Checks everything first and tells you what to fix. Ctrl+C stops the app.

param([switch]$Secure)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py  = ".\.venv\Scripts\python.exe"
$url = "http://127.0.0.1:5100"

function Fail($msg) { Write-Host "`n$msg" -ForegroundColor Red; exit 1 }

Write-Host "== Extreme & Change Analytics Lab ==" -ForegroundColor Cyan
if (-not (Test-Path $py)) { Fail "No .venv found. Run .\rebuild.ps1 first." }

# 1. free port 5100 (old python run.py or the .exe would answer instead)
Get-Process -Name ExtremeAnalyticsLab -ErrorAction SilentlyContinue | Stop-Process -Force
Get-NetTCPConnection -LocalPort 5100 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

# 2. mode for this run only (overrides config.ini / config.local.ini)
if ($Secure) { $env:APP_MODE = "server" } else { $env:APP_MODE = "local" }

# 3. check the app really switches
$checkPy = Join-Path $env:TEMP "tal_start_check.py"
@"
import sys
sys.path.insert(0, r'$PSScriptRoot')
try:
    from app import create_app
    a = create_app()
except Exception as e:
    print('ERROR', type(e).__name__, e)
    sys.exit(0)
login = any(r.rule == '/login' for r in a.url_map.iter_rules())
print('OK', a.config.get('APP_MODE'), login)
"@ | Set-Content -Path $checkPy -Encoding ASCII
$check = (& $py $checkPy | Select-Object -Last 1)
Remove-Item $checkPy -ErrorAction SilentlyContinue

$parts = "$check".Split(" ", 3)
if (-not $check) { Fail "The pre-check printed nothing - run  .\.venv\Scripts\python.exe run.py  to see the error." }
if ($parts[0] -eq "ERROR") {
    if ("$check" -match "password|secret") {
        Fail ("Login cannot start: $($parts[2])`n`nAdd to config.local.ini (notepad config.local.ini):`n" +
              "  [server]`n  password = your-password`n  secret_key = <run: python -c `"import secrets; print(secrets.token_hex(32))`">")
    }
    Fail "The app could not start: $check"
}
if ($Secure) {
    if ($parts[1] -ne "server" -or $parts[2] -ne "True") {
        Fail ("Server mode did not switch on (app reports: $check).`n" +
              "The login is not hooked in. Run:  python apply_web_deployment.py`nthen .\start.ps1 -Secure again.")
    }
    Write-Host "Mode: SERVER (login required)" -ForegroundColor Green
    $open = "$url/login"
} else {
    Write-Host "Mode: LOCAL (no login)" -ForegroundColor Green
    $open = $url
}

# 4. open the browser once the app answers
Start-Job -ArgumentList $url, $open -ScriptBlock {
    param($u, $o)
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try { Invoke-WebRequest -Uri "$u/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $o; return } catch { }
        try { Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2 -MaximumRedirection 0 | Out-Null; Start-Process $o; return } catch {
            if ($_.Exception.Response) { Start-Process $o; return } }
    }
} | Out-Null

Write-Host "Starting at $url  (Ctrl+C to stop; press Ctrl+F5 in the browser)" -ForegroundColor Cyan
try {
    & $py run.py
} finally {
    Remove-Item Env:APP_MODE -ErrorAction SilentlyContinue
}
