#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# aiogram и pydantic поддерживают Python 3.10–3.14: ищем подходящую версию
find_python() {
    for cmd in python3.13 python3.12 python3.14 python3.11 python3.10 python3; do
        if command -v "$cmd" >/dev/null 2>&1 &&
            "$cmd" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 14)))' 2>/dev/null; then
            echo "$cmd"
            return
        fi
    done
}

# .venv/.installed появляется только после успешной установки, поэтому прерванная установка повторится
if [ ! -f .venv/.installed ]; then
    PY=$(find_python)
    if [ -z "$PY" ]; then
        echo "Нужен Python версии 3.10–3.14, сейчас установлен: $(python3 --version 2>&1)"
        echo "Скачайте Python 3.13 здесь: https://www.python.org/downloads/macos/"
        exit 1
    fi
    echo "Устанавливаю зависимости ($($PY --version)), это нужно только при первом запуске..."
    rm -rf .venv
    "$PY" -m venv .venv
    .venv/bin/pip install -r requirements.txt
    touch .venv/.installed
fi
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Заполните BOT_TOKEN и OPENAI_API_KEY в файле .env и запустите снова."
    exit 0
fi
exec .venv/bin/python bot.py
