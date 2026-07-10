# Упаковка проекта для VPS без мусора (4tochki HTML-кэш и т.д.)
# Запуск на ПК:  powershell -File deploy\pack-for-vps.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Staging = Join-Path $env:TEMP "avito_tires_parser_deploy"
$Zip = Join-Path $env:USERPROFILE "Desktop\avito_tires_parser_vps.zip"

$ExcludeDirs = @(
    "__pycache__", ".pytest_cache", ".browser_profile", ".venv", "venv", ".git",
    "data\4tochki_html_cache", "output", "logs", "tests"
)
$ExcludeFiles = @(
    "secrets.local.yaml", "model_descriptions.yaml", "data\4tochki_descriptions.json"
)

if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
New-Item -ItemType Directory -Path $Staging | Out-Null

Write-Host "Копируем в $Staging ..."

robocopy $Root $Staging /E /NFL /NDL /NJH /NJS /nc /ns /np `
    /XD $($ExcludeDirs -join " ") `
    /XF $($ExcludeFiles -join " ") `
    | Out-Null

# robocopy exit 0-7 = ok
if ($LASTEXITCODE -gt 7) { throw "robocopy failed: $LASTEXITCODE" }

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $Zip -Force

Write-Host ""
Write-Host "Готово: $Zip"
Write-Host ""
Write-Host "На сервер (один файл вместо 4000+):"
Write-Host "  scp $Zip root@185.198.152.108:/tmp/"
Write-Host ""
Write-Host "На сервере:"
Write-Host "  cd /opt && rm -rf avito_tires_parser && mkdir avito_tires_parser"
Write-Host "  unzip /tmp/avito_tires_parser_vps.zip -d /opt/avito_tires_parser"
Write-Host "  scp secrets.local.yaml root@185.198.152.108:/opt/avito_tires_parser/"
