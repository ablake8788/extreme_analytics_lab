# deploy_windows_server.ps1 - install or update the Extreme & Change Analytics Lab
# on a Windows Server with Plesk / IIS (GoDaddy Windows VPS).
#
# Run ON THE SERVER in PowerShell "Run as administrator", from the folder that
# holds extreme_server.zip and this script:
#
#   .\deploy_windows_server.ps1 -Domain analytics.carfourless.com
#
# What it does (safe to run again for updates):
#   1. extracts extreme_server.zip to C:\apps\extreme_analytics_lab (keeps config.local.ini)
#   2. creates .venv with Python 3.12 and installs the packages + waitress
#   3. creates config.local.ini (server mode, random secret key) if missing
#   4. checks the app starts in server mode (login on)
#   5. registers a startup task that runs the app on 127.0.0.1:5100 (not public)
#   6. enables the IIS ARR proxy and writes web.config for the Plesk site
#   7. tests http://127.0.0.1:5100/healthz

param(
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$ZipPath  = (Join-Path $PSScriptRoot "extreme_server.zip"),
    [string]$AppDir   = "C:\apps\extreme_analytics_lab",
    [string]$Python   = "C:\Python312\python.exe",
    [int]$Port        = 5100,
    [string]$TaskName = "ExtremeAnalyticsLab"
)

$ErrorActionPreference = "Stop"
function Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }
function Fail($t) { Write-Host "`n$t" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- 0. checks
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail "Run this in PowerShell opened with 'Run as administrator'." }
if (-not (Test-Path $ZipPath)) { Fail "extreme_server.zip not found at $ZipPath" }
if (-not (Test-Path $Python)) { Fail "Python not found at $Python - install Python 3.12 for all users to C:\Python312." }
$ver = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.9") { Fail "Python $ver is too old - need 3.9 or newer (use C:\Python312\python.exe)." }
Write-Host "Python $ver at $Python" -ForegroundColor Green

# ---------------------------------------------------------------- 1. extract
Step "1. Extract the app to $AppDir"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Force $AppDir | Out-Null
$keep = Join-Path $AppDir "config.local.ini"
$keepCopy = $null
if (Test-Path $keep) { $keepCopy = Get-Content $keep -Raw }
Expand-Archive -Path $ZipPath -DestinationPath $AppDir -Force
if ($keepCopy) { [IO.File]::WriteAllText($keep, $keepCopy) }
foreach ($d in "uploads", "results", "logs") { New-Item -ItemType Directory -Force (Join-Path $AppDir $d) | Out-Null }
Write-Host "Extracted. config.local.ini kept: $([bool]$keepCopy)" -ForegroundColor Green

# ---------------------------------------------------------------- 2. venv + packages
Step "2. Python environment and packages"
$venvPy = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { & $Python -m venv (Join-Path $AppDir ".venv") }
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r (Join-Path $AppDir "requirements.txt") waitress
if ($LASTEXITCODE -ne 0) { Fail "Package install failed - see the errors above." }

# ---------------------------------------------------------------- 3. private settings
Step "3. Private settings (config.local.ini)"
if (-not (Test-Path $keep)) {
    $secret = & $venvPy -c "import secrets; print(secrets.token_hex(32))"
    $iniText = @"
; config.local.ini - PRIVATE settings on this server only (never in git)
[app]
mode = server

[server]
password = CHANGE-ME
secret_key = $secret
domain = $Domain
session_hours = 12
upload_max_age_hours = 24

[openai]
; api_key = sk-...

[reports]
; reports are returned to the browser; no server copy needed
"@
    [IO.File]::WriteAllText($keep, $iniText)
    Write-Host "Created config.local.ini. Set the sign-in password and OpenAI key now (Notepad opens)." -ForegroundColor Yellow
    Start-Process notepad.exe $keep -Wait
}
# lock the file down: Administrators and SYSTEM only
icacls $keep /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" | Out-Null

# ---------------------------------------------------------------- 4. pre-check
Step "4. Check the app starts with the login on"
$check = Join-Path $env:TEMP "tal_server_check.py"
@"
import os, sys
os.chdir(r'$AppDir'); sys.path.insert(0, r'$AppDir')
os.environ['APP_CONFIG_LOCAL'] = r'$keep'
try:
    import passenger_wsgi as p
    a = p.application
    print('OK', a.config.get('APP_MODE'), any(r.rule == '/login' for r in a.url_map.iter_rules()))
except Exception as e:
    print('ERROR', type(e).__name__, e)
"@ | Set-Content -Path $check -Encoding ASCII
$res = (& $venvPy $check | Select-Object -Last 1)
Remove-Item $check -ErrorAction SilentlyContinue
if ("$res" -notmatch "^OK server True") {
    Fail "The app did not start in server mode: $res`nFix config.local.ini ($keep): [server] password and secret_key, then run this script again."
}
if (Select-String -Path $keep -Pattern '^\s*password\s*=\s*CHANGE-ME' -Quiet) {
    Fail "Set a real sign-in password in $keep ([server] password), then run this script again."
}
Write-Host "Server mode with login: OK" -ForegroundColor Green

# ---------------------------------------------------------------- 5. startup task
Step "5. Run the app in the background (task '$TaskName', 127.0.0.1:$Port)"
$runner = Join-Path $AppDir "run_server.cmd"
@"
@echo off
cd /d "$AppDir"
set APP_MODE=server
"$venvPy" -m waitress --listen=127.0.0.1:$Port --threads=8 passenger_wsgi:application >> "$AppDir\logs\server.log" 2>&1
"@ | Set-Content -Path $runner -Encoding ASCII

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`"" -WorkingDirectory $AppDir
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    Start-Sleep -Seconds 2
    try { $r = Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 3; $ok = ($r.Content -match "ok") } catch { }
}
if (-not $ok) { Fail "The app did not answer on 127.0.0.1:$Port. See $AppDir\logs\server.log" }
Write-Host "App running on http://127.0.0.1:$Port (starts automatically after reboot)" -ForegroundColor Green

# ---------------------------------------------------------------- 6. IIS proxy
Step "6. IIS: enable ARR proxy and write web.config"
Import-Module WebAdministration
Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "enabled" -Value "True"
Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "preserveHostHeader" -Value "True"
Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "timeout" -Value "00:05:00"
# allow web.config to tell the app the visitor used HTTPS (X-Forwarded-Proto)
$allowed = Get-WebConfiguration -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/rewrite/allowedServerVariables/add" |
    Where-Object { $_.name -eq "HTTP_X_FORWARDED_PROTO" }
if (-not $allowed) {
    Add-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/rewrite/allowedServerVariables" -Name "." -Value @{ name = "HTTP_X_FORWARDED_PROTO" }
}

$webConfig = Join-Path $AppDir "iis\web.config"
New-Item -ItemType Directory -Force (Split-Path $webConfig) | Out-Null
@"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="HTTPS only" stopProcessing="true">
          <match url="(.*)" />
          <conditions><add input="{HTTPS}" pattern="off" /></conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
        <rule name="Extreme Analytics Lab" stopProcessing="true">
          <match url="(.*)" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
          </serverVariables>
          <action type="Rewrite" url="http://127.0.0.1:$Port/{R:1}" />
        </rule>
      </rules>
    </rewrite>
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="62914560" />
      </requestFiltering>
    </security>
    <httpErrors existingResponse="PassThrough" />
  </system.webServer>
</configuration>
"@ | Set-Content -Path $webConfig -Encoding UTF8

$siteRoot = "C:\Inetpub\vhosts\$Domain\httpdocs"
if (Test-Path $siteRoot) {
    $existing = Join-Path $siteRoot "web.config"
    if (Test-Path $existing) { Copy-Item $existing "$existing.bak" -Force }
    Copy-Item $webConfig $existing -Force
    Write-Host "web.config installed in $siteRoot" -ForegroundColor Green
} else {
    Write-Host "Plesk site folder not found ($siteRoot)." -ForegroundColor Yellow
    Write-Host "Add the domain in Plesk first, then copy $webConfig into its httpdocs folder." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 7. done
Step "Done"
Write-Host "Local check : http://127.0.0.1:$Port/healthz  -> ok"
Write-Host "Website     : https://$Domain   (needs the Plesk domain + Let's Encrypt SSL)"
Write-Host "App folder  : $AppDir"
Write-Host "Settings    : $keep"
Write-Host "Log         : $AppDir\logs\server.log"
Write-Host "Restart app : Stop-ScheduledTask $TaskName; Start-ScheduledTask $TaskName"
