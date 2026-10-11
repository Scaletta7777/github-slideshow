import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Config:
    bot_token: str
    openai_api_key: str
    allowed_user_ids: set[int]
    image_model: str
    image_quality: str
    font_path: str | None
    card_language: str
    text_model: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip().strip("\"'«»“”")
    key = os.getenv("OPENAI_API_KEY", "").strip().strip("\"'«»“”")
    if not token or not key:
        raise SystemExit("Заполните BOT_TOKEN и OPENAI_API_KEY в файле .env (см. .env.example)")
    # при вставке из Терминала к ключу иногда прилипает мусор («s:sk-proj-…») — отрезаем всё до «sk-»
    if m := re.search(r"sk-[\w-]{20,}", key):
        key = m.group(0)
    else:
        raise SystemExit("OPENAI_API_KEY в файле .env должен начинаться с sk-. Проверьте ключ на platform.openai.com")
    # то же для токена: он начинается с цифр бота
    if m := re.search(r"\d{5,}:[\w-]{30,}", token):
        token = m.group(0)
    if not re.fullmatch(r"\d{5,}:[\w-]{30,}", token) or token.startswith("123456789:"):
        raise SystemExit(
            "BOT_TOKEN в файле .env выглядит неправильно. Он должен быть вида 7712345678:AAH... "
            "Скопируйте его заново в @BotFather: /mybots → ваш бот → API Token."
        )
    return Config(
        bot_token=token,
        openai_api_key=key,
        allowed_user_ids=_ids(os.getenv("ALLOWED_USER_IDS", "")),
        image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2").strip(),
        image_quality=os.getenv("OPENAI_IMAGE_QUALITY", "high").strip(),
        font_path=os.getenv("FONT_PATH", "").strip() or None,
        card_language=os.getenv("CARD_LANGUAGE", "Russian").strip() or "Russian",
        text_model=os.getenv("OPENAI_TEXT_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini",
    )
