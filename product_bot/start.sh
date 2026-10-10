#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    echo "Устанавливаю зависимости, это нужно только при первом запуске..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Заполните BOT_TOKEN и OPENAI_API_KEY в файле .env и запустите снова."
    exit 0
fi
exec .venv/bin/python bot.py
