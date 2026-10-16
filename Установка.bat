@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Python: команда python, а если её нет (или это заглушка Microsoft Store) — лаунчер py
set PY=python
python --version >nul 2>&1 || set PY=py
%PY% --version >nul 2>&1 || (echo Не найден Python 3.11+. Установите его с python.org, отметив «Add python.exe to PATH». & pause & exit /b 1)
echo Устанавливаю библиотеки Python...
%PY% -m pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo Готово. Дальше: установите и запустите Docker Desktop, затем «Запуск DreamGoods.bat».
pause
