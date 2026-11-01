@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Separate test database and files. Existing Dev-GPT data is reused.
set "DATABASE_URL=postgresql+psycopg://studio:studio@127.0.0.1:5433/dreamgoods_dev_gpt"
set "DREAMGOODS_HOST=127.0.0.1"
set "DREAMGOODS_PORT=8766"
set "DREAMGOODS_DISABLE_LEGACY_IMPORT=true"
set "STORAGE=local"
set "STORAGE_DIR=%~dp0data-dev-gpt\files"
set "DREAMGOODS_LOG_DIR=%~dp0logs-dev-gpt"
set "DREAMGOODS_EXPORT_DIR=%~dp0exports-dev-gpt"

set "DG_PY=python"
if exist "%~dp0.venv\Scripts\python.exe" (
  set DG_PY="%~dp0.venv\Scripts\python.exe"
) else (
  python --version >nul 2>&1
  if errorlevel 1 set "DG_PY=py -3"
)
%DG_PY% --version >nul 2>&1
if errorlevel 1 (
  echo Не найден Python. Установите Python 3.11+ или создайте .venv.
  pause
  exit /b 1
)

echo Запускаю Dev-GPT: http://127.0.0.1:8766
echo PostgreSQL: 5433, отдельный том dreamgoods_dev_gpt_pgdata.
docker compose -p dreamgoods-dev-gpt -f docker-compose.dev-gpt.yml up -d --wait
if errorlevel 1 (
  echo Не удалось запустить тестовую базу. Проверьте Docker Desktop и свободен ли порт 5433.
  pause
  exit /b 1
)
%DG_PY% run_dreamgoods.py %*
set "DG_EXIT=%ERRORLEVEL%"
pause
exit /b %DG_EXIT%
