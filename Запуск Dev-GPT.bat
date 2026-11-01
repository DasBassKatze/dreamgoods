@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DATABASE_URL=postgresql+psycopg://studio:studio@127.0.0.1:5433/dreamgoods_dev_gpt
set DREAMGOODS_PORT=8766
set DREAMGOODS_DISABLE_LEGACY_IMPORT=true
set STORAGE=local
set STORAGE_DIR=%~dp0data-dev-gpt\files
set DREAMGOODS_BACKUP_DIR=%~dp0backups-dev-gpt
set DREAMGOODS_LOG_DIR=%~dp0logs-dev-gpt
set DREAMGOODS_EXPORT_DIR=%~dp0exports-dev-gpt
docker compose -f docker-compose.dev-gpt.yml up -d --wait
if errorlevel 1 goto error
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe run_dreamgoods.py
) else (
  python run_dreamgoods.py
)
:error
pause
