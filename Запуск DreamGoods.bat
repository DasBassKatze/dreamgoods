@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Python: команда python, а если её нет (или это заглушка Microsoft Store) — лаунчер py
set PY=python
python --version >nul 2>&1 || set PY=py
%PY% --version >nul 2>&1 || (echo Не найден Python 3.11+. Установите его с python.org, отметив «Add python.exe to PATH». & pause & exit /b 1)
if not exist .env copy .env.example .env >nul
echo Запускаю базу данных PostgreSQL (Docker Desktop должен быть запущен)...
rem контейнер базы прежней версии (проект «studio») держит порт 5432 — останавливаем его, данные в томе сохраняются
docker stop studio-postgres-1 >nul 2>&1
docker rm studio-postgres-1 >nul 2>&1
docker compose up -d --wait
if errorlevel 1 (echo Не удалось запустить базу в Docker. Откройте Docker Desktop, дождитесь Engine running и повторите. Если не скачивается образ postgres — см. комментарий в docker-compose.yml. & pause & exit /b 1)
%PY% run_dreamgoods.py %*
pause
