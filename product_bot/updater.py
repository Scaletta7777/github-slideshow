"""Перезапуск и обновление бота из Telegram (/restart, /update)."""

import asyncio
import os
import ssl
import sys
from pathlib import Path

import aiohttp
import certifi

HERE = Path(__file__).parent
UPDATE_URL = os.getenv(
    "UPDATE_URL",
    "https://raw.githubusercontent.com/Scaletta7777/github-slideshow/claude/aidentika-bot-clone-fwg076/product_bot/",
)


async def fetch_updates() -> list[str]:
    """Скачивает файлы из UPDATE_URL (список — в файле FILES), записывает изменённые и возвращает их имена."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx)) as session:

        async def get(name: str) -> bytes:
            async with session.get(UPDATE_URL + name, timeout=aiohttp.ClientTimeout(total=60)) as r:
                r.raise_for_status()
                return await r.read()

        names = [n.strip() for n in (await get("FILES")).decode().splitlines() if n.strip()]
        contents = dict(zip(names, await asyncio.gather(*(get(n) for n in names))))
    changed = []
    for name, data in contents.items():
        path = HERE / name
        if not path.exists() or path.read_bytes() != data:
            changed.append(name)
    for name in changed:  # пишем только после того, как всё скачалось
        (HERE / name).write_bytes(contents[name])
    if "start.sh" in changed:
        os.chmod(HERE / "start.sh", 0o755)
    return changed


async def install_requirements() -> str:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-q", "-r", str(HERE / "requirements.txt"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(out.decode(errors="replace")[-1500:])
    return out.decode(errors="replace")


def restart_process(notify_chat_id: int | None) -> None:
    """Заменяет текущий процесс новым запуском bot.py (тот же Python, то же окно Терминала)."""
    if notify_chat_id:
        os.environ["BOT_RESTARTED_CHAT"] = str(notify_chat_id)
    os.chdir(HERE)
    os.execv(sys.executable, [sys.executable, str(HERE / "bot.py")])
