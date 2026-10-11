"""Пользователи, которым владелец выдал доступ из Telegram. Хранится в access.json рядом с ботом."""

import json
from pathlib import Path

FILE = Path(__file__).parent / "access.json"


def load() -> dict[int, str]:
    try:
        return {int(k): v for k, v in json.loads(FILE.read_text(encoding="utf-8")).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(users: dict[int, str]) -> None:
    FILE.write_text(json.dumps({str(k): v for k, v in users.items()}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def add(user_id: int, name: str) -> None:
    _save({**load(), user_id: name})


def remove(user_id: int) -> None:
    users = load()
    users.pop(user_id, None)
    _save(users)
