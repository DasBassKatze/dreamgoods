@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
where npm >nul 2>nul
if errorlevel 1 (
  echo Не найден Node.js. Установите LTS-версию с https://nodejs.org и запустите этот файл снова.
  pause
  exit /b 1
)
echo Ставлю зависимости интерфейса (первый раз — пара минут)...
call npm install
if errorlevel 1 goto fail
echo Собираю интерфейс в dreamgoods\web ...
call npm run build
if errorlevel 1 goto fail
echo Готово. Перезапустите DreamGoods, чтобы увидеть изменения.
pause
exit /b 0
:fail
echo Сборка не удалась — смотрите сообщения выше.
pause
exit /b 1
