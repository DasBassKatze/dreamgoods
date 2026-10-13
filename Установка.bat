@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Устанавливаю библиотеки Python...
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo Готово. Дальше: установите и запустите Docker Desktop, затем «Запуск DreamGoods.bat».
pause
