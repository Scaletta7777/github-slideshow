@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem .venv\.installed появляется только после успешной установки, поэтому прерванная установка повторится
if not exist .venv\.installed (
    echo Устанавливаю зависимости, это нужно только при первом запуске...
    if exist .venv rmdir /s /q .venv
    python -m venv .venv || (echo Не найден Python. Установите его с https://www.python.org/downloads/ & pause & exit /b 1)
    .venv\Scripts\python -m pip install -r requirements.txt || (echo Ошибка установки зависимостей & pause & exit /b 1)
    type nul > .venv\.installed
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
