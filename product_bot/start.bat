@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
    echo Устанавливаю зависимости, это нужно только при первом запуске...
    python -m venv .venv || (echo Не найден Python. Установите его с https://www.python.org/downloads/ & pause & exit /b 1)
    .venv\Scripts\python -m pip install -q -r requirements.txt
)
if not exist .env (
    copy .env.example .env >nul
    echo Заполните BOT_TOKEN и OPENAI_API_KEY в файле .env и запустите снова.
    notepad .env
    pause
    exit /b 0
)
.venv\Scripts\python bot.py
pause
