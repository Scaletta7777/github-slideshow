import os
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


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not token or not key:
        raise SystemExit("Заполните BOT_TOKEN и OPENAI_API_KEY в файле .env (см. .env.example)")
    return Config(
        bot_token=token,
        openai_api_key=key,
        allowed_user_ids=_ids(os.getenv("ALLOWED_USER_IDS", "")),
        image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2").strip(),
        image_quality=os.getenv("OPENAI_IMAGE_QUALITY", "high").strip(),
        font_path=os.getenv("FONT_PATH", "").strip() or None,
    )
