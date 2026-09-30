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

# Remove caches, backups and anything private
Get-ChildItem $stage -Recurse -Force -Include "__pycache__", "*.pyc", "*.bak", "config.local.ini" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $out) { Remove-Item -Force $out }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $out -Force
Remove-Item -Recurse -Force $stage

$size = [math]::Round((Get-Item $out).Length / 1KB)
Write-Host "Created $out ($size KB)" -ForegroundColor Green
Write-Host "Upload it to GoDaddy (web_deployment_steps.txt, step 7)." -ForegroundColor Cyan
