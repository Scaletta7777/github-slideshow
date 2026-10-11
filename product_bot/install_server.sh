#!/usr/bin/env bash
# Установка бота на Linux-сервер (Ubuntu / Debian) как фоновой службы systemd.
# Ставится в отдельную папку и отдельную службу — другие боты на сервере не затрагиваются.
#   curl -fsSLO <URL>/install_server.sh && bash install_server.sh
set -euo pipefail

DIR="${BOT_DIR:-$HOME/product_bot}"
SERVICE="${BOT_SERVICE:-product-bot}"
URL="${UPDATE_URL:-https://raw.githubusercontent.com/Scaletta7777/github-slideshow/claude/aidentika-bot-clone-fwg076/product_bot/}"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> Скачиваю бота в $DIR"
mkdir -p "$DIR"
cd "$DIR"
curl -fsSL "${URL}FILES" -o FILES
while read -r f; do
    [ -n "$f" ] && curl -fsSL "${URL}${f}" -o "$f"
done < FILES
chmod +x start.sh install_server.sh

find_python() {
    for cmd in python3.13 python3.12 python3.14 python3.11 python3.10 python3; do
        if command -v "$cmd" >/dev/null 2>&1 &&
            "$cmd" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 14)))' 2>/dev/null; then
            echo "$cmd"
            return
        fi
    done
}

PY=$(find_python)
if [ -z "$PY" ]; then
    echo "Нужен Python 3.10–3.14, сейчас: $(python3 --version 2>&1 || echo 'не установлен')."
    echo "На Ubuntu: $SUDO apt-get install -y python3 python3-venv"
    exit 1
fi

if [ ! -f .venv/.installed ]; then
    echo "==> Устанавливаю зависимости ($($PY --version))"
    rm -rf .venv
    if ! "$PY" -m venv .venv 2>/dev/null; then
        echo "==> Ставлю пакет venv для $PY"
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq "$(basename "$PY")-venv" || $SUDO apt-get install -y -qq python3-venv
        rm -rf .venv
        "$PY" -m venv .venv
    fi
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r requirements.txt
    touch .venv/.installed
fi

set_env() {  # set_env KEY VALUE — заменяет строку KEY=... в .env
    .venv/bin/python - "$1" "$2" <<'PY'
import re, sys
key, value = sys.argv[1], sys.argv[2].strip()
text = open(".env", encoding="utf-8").read()
line = f"{key}={value}"
text = re.sub(rf"(?m)^{key}=.*$", lambda m: line, text) if re.search(rf"(?m)^{key}=", text) else text + f"\n{line}\n"
open(".env", "w", encoding="utf-8").write(text)
PY
}

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "==> Настройка ключей (их можно поменять позже в $DIR/.env)"
    read -rp "Токен бота от @BotFather: " T
    read -rp "Ключ OpenAI (sk-...): " K
    read -rp "Ваш Telegram ID (если не знаете — оставьте пустым): " U
    set_env BOT_TOKEN "$T"
    set_env OPENAI_API_KEY "$K"
    set_env ALLOWED_USER_IDS "$U"
fi

if [ "${SKIP_SYSTEMD:-}" = "1" ]; then
    echo "==> SKIP_SYSTEMD=1: служба не создаётся. Запуск вручную: $DIR/.venv/bin/python $DIR/bot.py"
    exit 0
fi

echo "==> Создаю службу $SERVICE"
$SUDO tee "/etc/systemd/system/$SERVICE.service" >/dev/null <<EOF
[Unit]
Description=Product photo Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now "$SERVICE"
$SUDO systemctl restart "$SERVICE"
sleep 3
$SUDO systemctl --no-pager --lines=8 status "$SERVICE" || true

cat <<EOF

✅ Готово! Бот работает как служба «$SERVICE» и запускается сам после перезагрузки сервера.
   Логи:        $SUDO journalctl -u $SERVICE -f
   Перезапуск:  $SUDO systemctl restart $SERVICE   (или /restart в Telegram)
   Остановка:   $SUDO systemctl stop $SERVICE
   Ключи:       nano $DIR/.env   (после правки — перезапуск)
EOF
