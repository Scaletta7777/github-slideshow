"""Библиотека образцов: карточки, которые нравятся продавцу. Хранится в папке styles/ рядом с ботом."""

import json
import uuid
from pathlib import Path

DIR = Path(__file__).parent / "styles"
INDEX = DIR / "styles.json"


def load() -> list[dict]:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(items: list[dict]) -> None:
    DIR.mkdir(exist_ok=True)
    INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add(name: str, description: str, image_jpeg: bytes) -> dict:
    item = {"id": "ref_" + uuid.uuid4().hex[:8], "name": name, "description": description}
    DIR.mkdir(exist_ok=True)
    (DIR / f"{item['id']}.jpg").write_bytes(image_jpeg)
    _save(load() + [item])
    return item


def get(style_id: str) -> dict | None:
    return next((i for i in load() if i["id"] == style_id), None)


def image(style_id: str) -> bytes:
    return (DIR / f"{style_id}.jpg").read_bytes()


def remove(style_id: str) -> None:
    _save([i for i in load() if i["id"] != style_id])
    (DIR / f"{style_id}.jpg").unlink(missing_ok=True)
