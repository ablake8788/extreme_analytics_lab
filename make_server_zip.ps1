# make_server_zip.ps1 - builds extreme_server.zip to upload to GoDaddy.
# Run from the extreme_analytics_lab folder. Contains only what the server
# needs; never includes config.local.ini, .venv, tests, build or dist.

$ErrorActionPreference = "Stop"
$out = "extreme_server.zip"
$items = @("app", "run.py", "passenger_wsgi.py", "requirements.txt", "config.ini")

Write-Host "== Building $out for GoDaddy ==" -ForegroundColor Cyan
foreach ($i in $items) {
    if (-not (Test-Path $i)) { Write-Host "Missing $i - run this from the project folder." -ForegroundColor Red; exit 1 }
}
if (Select-String -Path "config.ini" -Pattern '^\s*mode\s*=\s*server' -Quiet) {
    Write-Host "Note: config.ini has mode = server. That is fine for the server, but keep mode = local for the .exe." -ForegroundColor DarkYellow
}
if (Select-String -Path "config.ini" -Pattern '^\s*(password|secret_key)\s*=' -Quiet) {
    Write-Host "STOP: config.ini contains a password or secret_key. Move them to config.local.ini (local) or cPanel environment variables (server)." -ForegroundColor Red
    exit 1
}

$stage = Join-Path $env:TEMP "extreme_server_stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory $stage | Out-Null
foreach ($i in $items) { Copy-Item $i -Destination $stage -Recurse -Force }
# reference document for AI reports (config.ini: [reports] reference_document)
if (Test-Path "info_main\reference") {
    New-Item -ItemType Directory (Join-Path $stage "info_main") -Force | Out-Null
    Copy-Item "info_main\reference" -Destination (Join-Path $stage "info_main") -Recurse -Force
}

# Remove caches, backups and anything private
Get-ChildItem $stage -Recurse -Force -Include "__pycache__", "*.pyc", "*.bak", "config.local.ini" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $out) { Remove-Item -Force $out }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $out -Force
Remove-Item -Recurse -Force $stage

$size = [math]::Round((Get-Item $out).Length / 1KB)
Write-Host "Created $out ($size KB)" -ForegroundColor Green

# Windows Server (GoDaddy VPS with Plesk): a folder with everything to copy to the server
$pkg = "deploy_package"
if (Test-Path $pkg) { Remove-Item -Recurse -Force $pkg }
New-Item -ItemType Directory $pkg | Out-Null
Copy-Item $out $pkg
if (Test-Path "deploy_windows_server.ps1") { Copy-Item "deploy_windows_server.ps1" $pkg }
Write-Host "Created $pkg\ with extreme_server.zip + deploy_windows_server.ps1" -ForegroundColor Green
Write-Host "Copy the deploy_package folder to the server (Remote Desktop) and run there, as administrator:" -ForegroundColor Cyan
Write-Host "  .\deploy_windows_server.ps1 -Domain your.domain.com" -ForegroundColor Cyan
