@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo === %date% %time% === >> logs\run.log

REM Остатки Google/БД -> posting -> autoload (без парсера Avito)
python build_stock.py >> logs\run.log 2>&1
if errorlevel 1 exit /b %errorlevel%
python process_manager_inbox.py >> logs\run.log 2>&1
if errorlevel 1 exit /b %errorlevel%
python compare_prices.py >> logs\run.log 2>&1
if errorlevel 1 exit /b %errorlevel%
python build_autoload.py >> logs\run.log 2>&1
