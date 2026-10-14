# deploy.ps1 - one script for a release, run on the PC from the extreme_analytics_lab folder.
#
#   .\deploy.ps1                      tests -> .exe -> server package (deploy_package\)
#   .\deploy.ps1 -SkipExe             tests -> server package only (faster)
#   .\deploy.ps1 -SkipServer          tests -> .exe only
#   .\deploy.ps1 -Commit "message"    ... and commit + push to GitHub (branch dev)
#   .\deploy.ps1 -Pull                git pull origin dev first
#
# A copy of the server package is also saved as one zip in the unzip folder
# (-ZipFolder), named deploy_package_YYYYMMDD-HHMM.zip.
#
# Stops at the first failing step. Never copies config.local.ini anywhere.
# The last step prints the commands to run on the server (Remote Desktop).

param(
    [switch]$SkipExe,
    [switch]$SkipServer,
    [switch]$Pull,
    [string]$Commit = "",
    [string]$Domain = "app.titaniumanalyses.com",
    [string]$ZipFolder = "C:\Users\ablak\MorrisAutoGroup Dropbox\Alexander Blake\MorrisUniversalAutoGroup\ara\ara\Ange\projects\ara\Titanium Intelligent Solution\Titanium Analytics\working\unzip"
)

$ErrorActionPreference = "Continue"   # native tools (python, git) report errors by exit code; checked after each step
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
$step = 0
function Step($text) { $script:step++; Write-Host ""; Write-Host "== $script:step. $text ==" -ForegroundColor Cyan }
function Fail($text) { Write-Host ""; Write-Host "STOPPED: $text" -ForegroundColor Red; exit 1 }
function Ok($text)   { Write-Host $text -ForegroundColor Green }

Write-Host "== Extreme & Change Analytics Lab - deploy ==" -ForegroundColor Cyan
Write-Host "Folder: $PSScriptRoot"

# ---------------------------------------------------------------- checks
Step "Checks"
if (-not (Test-Path $py)) { Fail ".venv not found. Run .\rebuild.ps1 once, then run this script again." }
foreach ($f in @("app\services\report_xlsx.py", "app\services\report_xlsx_charts.py", "app\routes\ai_report.py")) {
    if (-not (Test-Path $f)) { Fail "$f is missing - the Excel report update is not in this folder." }
}
if (Select-String -Path "config.ini" -Pattern '^\s*(password|secret_key|api_key)\s*=\s*\S' -Quiet) {
    Fail "config.ini contains a password, secret_key or api_key. Move it to config.local.ini (never in git)."
}
$first = Get-Content "app\config.py" -TotalCount 1
if ($first -notmatch '^(import|from|"""|#)') { Fail "app\config.py line 1 looks wrong: '$first' (a pasted command?)." }
& $py -c "import openpyxl, matplotlib, PIL, docx, flask, pandas" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing missing packages ..." -ForegroundColor DarkYellow
    & $py -m pip install -q -r requirements.txt pytest
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed (Dropbox lock? Pause Dropbox and run .\rebuild.ps1)." }
}
Ok "Checks passed."

# ---------------------------------------------------------------- git pull
if ($Pull) {
    Step "Get the latest code (git pull)"
    git checkout dev
    git pull origin dev
    if ($LASTEXITCODE -ne 0) { Fail "git pull failed - run 'git stash', then this script again, then 'git stash pop'." }
}

# ---------------------------------------------------------------- tests
Step "Tests"
Stop-Process -Name ExtremeAnalyticsLab -ErrorAction SilentlyContinue
& $py -m pytest tests -q -p no:warnings
if ($LASTEXITCODE -ne 0) { Fail "Tests failed - fix the errors above first. Nothing was built." }
Ok "All tests passed."

# ---------------------------------------------------------------- .exe
if (-not $SkipExe) {
    Step "Build the desktop .exe"
    if (-not (Test-Path ".\build.ps1")) { Fail "build.ps1 not found." }
    & .\build.ps1
    if (-not (Test-Path "dist\ExtremeAnalyticsLab.exe")) { Fail "build.ps1 did not create dist\ExtremeAnalyticsLab.exe." }
    $exe = Get-Item "dist\ExtremeAnalyticsLab.exe"
    Ok ("Built {0} ({1:N0} MB, {2})" -f $exe.Name, ($exe.Length / 1MB), $exe.LastWriteTime)
}

# ---------------------------------------------------------------- server package
if (-not $SkipServer) {
    Step "Build the server package (deploy_package\)"
    & .\make_server_zip.ps1
    $zip = "deploy_package\extreme_server.zip"
    if (-not (Test-Path $zip)) { Fail "make_server_zip.ps1 did not create $zip." }
    # check the new Excel report code is inside the package
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead((Resolve-Path $zip))
    $names = $z.Entries | ForEach-Object { $_.FullName -replace '\\', '/' }
    $z.Dispose()
    foreach ($need in @("app/services/report_xlsx.py", "app/services/report_xlsx_charts.py", "app/routes/ai_report.py", "app/static/js/ai_report.js")) {
        if (-not ($names -contains $need)) { Fail "$need is not in $zip." }
    }
    if ($names | Where-Object { $_ -like "*config.local.ini" }) { Fail "$zip contains config.local.ini - it must never be uploaded." }
    Ok ("Package OK: deploy_package\ ({0:N0} KB zip), Excel report code included." -f ((Get-Item $zip).Length / 1KB))
    # one-file copy for the unzip folder: deploy_package_YYYYMMDD-HHMM.zip (extreme_server.zip + deploy_windows_server.ps1)
    if ($ZipFolder) {
        if (-not (Test-Path $ZipFolder)) { New-Item -ItemType Directory -Force $ZipFolder | Out-Null }
        $stamp = Get-Date -Format "yyyyMMdd-HHmm"
        $copy = Join-Path $ZipFolder "deploy_package_$stamp.zip"
        Compress-Archive -Path "deploy_package\*" -DestinationPath $copy -Force
        Ok "Copy saved: $copy"
    }
}

# ---------------------------------------------------------------- git commit + push
if ($Commit) {
    Step "Commit and push to GitHub (dev)"
    git add -A
    $private = git diff --cached --name-only | Where-Object { $_ -match 'config\.local\.ini|\.venv/|^dist/|^build/|^deploy_package/|\.bak$' }
    if ($private) { git reset -q; Fail "These must not be committed: $($private -join ', '). Add them to .gitignore." }
    $secret = git grep --cached -n -I -E "sk-[A-Za-z0-9_-]{20,}"
    if ($secret) { git reset -q; Fail "An API key is staged: $secret" }
    git commit -m $Commit
    git push origin dev 2>&1 | Out-String | Write-Host
    if ($LASTEXITCODE -ne 0) { Fail "git push failed - see the message above." }
    Ok "Pushed to origin/dev."
}

# ---------------------------------------------------------------- what next
Step "Next"
if (-not $SkipExe) {
    Write-Host "PC (.exe):     .\launch.ps1"
}
Write-Host "PC (source):   .\start.ps1          or with login: .\start.ps1 -Secure"
if (-not $SkipServer) {
    Write-Host ""
    Write-Host "Server (Remote Desktop):" -ForegroundColor Cyan
    Write-Host "  1. Copy BOTH files from deploy_package\ to C:\Users\artak\Downloads on the server (Replace)."
    Write-Host "     (or copy the one zip from the unzip folder and extract it there: Expand-Archive <zip> -DestinationPath . -Force)"
    Write-Host "  2. On the server, NEW PowerShell window as Administrator, paste:"
    Write-Host ""
    Write-Host "     cd C:\Users\artak\Downloads" -ForegroundColor Yellow
    Write-Host "     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force" -ForegroundColor Yellow
    Write-Host "     Remove-Item Env:APP_MODE -ErrorAction SilentlyContinue" -ForegroundColor Yellow
    Write-Host "     Get-ChildItem *.ps1 | Unblock-File" -ForegroundColor Yellow
    Write-Host "     .\deploy_windows_server.ps1 -Domain $Domain" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  3. Test: https://$Domain  (private window) -> AI report -> Generate AI report (Excel)."
    explorer.exe (Resolve-Path "deploy_package")
}
Ok "Done."
