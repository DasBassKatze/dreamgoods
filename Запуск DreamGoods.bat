@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
echo Запускаю базу данных PostgreSQL (Docker Desktop должен быть запущен)...
rem контейнер базы прежней версии (проект «studio») держит порт 5432 — останавливаем его, данные в томе сохраняются
docker stop studio-postgres-1 >nul 2>&1
docker rm studio-postgres-1 >nul 2>&1
docker compose up -d --wait
if errorlevel 1 (echo Не удалось запустить базу в Docker. Откройте Docker Desktop, дождитесь Engine running и повторите. Если не скачивается образ postgres — см. комментарий в docker-compose.yml. & pause & exit /b 1)
python run_dreamgoods.py %*
pause
