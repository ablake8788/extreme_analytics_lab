# test_all.ps1 - runs EVERY test for the Extreme & Change Analytics Lab.
#
#   .\test_all.ps1                  all tests, including building and starting the .exe
#   .\test_all.ps1 -SkipExe         everything except the .exe
#   .\test_all.ps1 -DataFile "C:\path\Jensen_Beach_AHU1_temperature.xlsx"
#
# 1. Unit tests (pytest)
# 2. Live, local mode:  app opens without login, upload + analysis
# 3. Live, server mode: sign-in, wrong/right password, API protection,
#                       upload + analysis while signed in, log out
# 4. Safety: server mode without a password refuses to start
# 5. GoDaddy start file: passenger_wsgi loads in server mode
# 6. The .exe: build.ps1, start it, opens without login, close it
#
# Your config.local.ini is never read or changed by these tests.

param(
    [string]$DataFile = "",
    [switch]$SkipExe
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$results = New-Object System.Collections.Generic.List[object]
function Add-Result([string]$name, [bool]$ok, [string]$note = "") {
    $results.Add([pscustomobject]@{ Test = $name; Result = $(if ($ok) { "PASS" } else { "FAIL" }); Note = $note })
}

Write-Host "== Extreme & Change Analytics Lab - all tests ==" -ForegroundColor Cyan

# ---------------------------------------------------------------- environment
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvOk = $false
if (Test-Path $py) {
    try { & $py -m pip --version *> $null; $venvOk = ($LASTEXITCODE -eq 0) } catch { $venvOk = $false }
}
if (-not $venvOk) {
    Write-Host "Virtual environment missing or damaged - running rebuild.ps1 setup is recommended." -ForegroundColor Yellow
    Write-Host "Creating .venv now..." -ForegroundColor Yellow
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
    python -m venv .venv
    try { Set-Content -Path ".venv" -Stream "com.dropbox.ignored" -Value 1 -ErrorAction Stop } catch { }
}
Write-Host "Checking packages..." -ForegroundColor Yellow
& $py -m pip install -q -r requirements.txt pytest
if ($LASTEXITCODE -ne 0) { Write-Host "Package install failed - see errors above." -ForegroundColor Red; exit 1 }

# Private settings must not change during the tests
$localIni = Join-Path $PSScriptRoot "config.local.ini"
$iniHashBefore = if (Test-Path $localIni) { (Get-FileHash $localIni).Hash } else { "" }

# ---------------------------------------------------------------- data file
if (-not $DataFile) {
    $searchDirs = @($PSScriptRoot, (Join-Path (Split-Path $PSScriptRoot -Parent) "unzip"), "$env:USERPROFILE\Downloads")
    $found = Get-ChildItem $searchDirs -Filter "Jensen_Beach_AHU1_temperature*.xlsx" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $DataFile = $found.FullName }
}
if ($DataFile -and (Test-Path $DataFile)) {
    Write-Host "Data file: $DataFile" -ForegroundColor DarkGray
} else {
    Write-Host "No data file found - upload/analysis checks will be skipped. Use -DataFile to set one." -ForegroundColor DarkYellow
    $DataFile = ""
}

# ---------------------------------------------------------------- 1. unit tests
Write-Host "`n== 1. Unit tests (pytest) ==" -ForegroundColor Cyan
& $py -m pytest tests -q
Add-Result "1. Unit tests (pytest)" ($LASTEXITCODE -eq 0)

# ---------------------------------------------------------------- 2-5. live checks
Write-Host "`n== 2-5. Live checks: local mode, server mode, safety, passenger_wsgi ==" -ForegroundColor Cyan
& $py tools\live_check.py $DataFile
Add-Result "2-5. Live checks (local, server/login, safety, passenger_wsgi)" ($LASTEXITCODE -eq 0)

# ---------------------------------------------------------------- 6. the .exe
if ($SkipExe) {
    Add-Result "6. .exe build and start" $true "skipped (-SkipExe)"
} else {
    Write-Host "`n== 6. Build and start the .exe ==" -ForegroundColor Cyan
    & .\build.ps1
    $built = ($LASTEXITCODE -eq 0) -and (Test-Path "dist\ExtremeAnalyticsLab.exe")
    Add-Result "6a. .exe builds" $built
    if ($built) {
        Get-Process -Name "ExtremeAnalyticsLab" -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 1
        $exe = Start-Process -FilePath (Resolve-Path "dist\ExtremeAnalyticsLab.exe") -PassThru -WindowStyle Minimized
        $page = $null
        for ($i = 0; $i -lt 60 -and -not $page; $i++) {
            Start-Sleep -Seconds 1
            try { $page = Invoke-WebRequest -Uri "http://127.0.0.1:5100/" -UseBasicParsing -TimeoutSec 3 } catch { }
        }
        $opens = $page -and $page.StatusCode -eq 200
        $noLogin = $opens -and ($page.Content -notmatch "Sign in")
        Add-Result "6b. .exe starts and opens" $opens
        Add-Result "6c. .exe has no login (local mode)" $noLogin
        Get-Process -Name "ExtremeAnalyticsLab" -ErrorAction SilentlyContinue | Stop-Process -Force
        if ($exe -and -not $exe.HasExited) { try { $exe.Kill() } catch { } }
    }
}

# ---------------------------------------------------------------- summary
$iniHashAfter = if (Test-Path $localIni) { (Get-FileHash $localIni).Hash } else { "" }
Add-Result "config.local.ini unchanged" ($iniHashBefore -eq $iniHashAfter)

Write-Host "`n== Summary ==" -ForegroundColor Cyan
$results | Format-Table -AutoSize
$failed = @($results | Where-Object { $_.Result -eq "FAIL" })
if ($failed.Count -eq 0) {
    Write-Host "ALL TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$($failed.Count) TEST GROUP(S) FAILED - scroll up for the details, or paste the output into the chat." -ForegroundColor Red
    exit 1
}
