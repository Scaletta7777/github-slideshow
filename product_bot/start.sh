#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
# .venv/.installed появляется только после успешной установки, поэтому прерванная установка повторится
if [ ! -f .venv/.installed ]; then
    echo "Устанавливаю зависимости, это нужно только при первом запуске..."
    rm -rf .venv
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    touch .venv/.installed
fi
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Заполните BOT_TOKEN и OPENAI_API_KEY в файле .env и запустите снова."
    exit 0
fi
exec .venv/bin/python bot.py
