"""Telegram-бот: фото товара -> профессиональная карточка для маркетплейса (OpenAI Images API)."""

import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message, TelegramObject
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder
from openai import OpenAIError
from PIL import Image

import infographic
from concepts import AI_INFOGRAPHIC_PROMPT, CONCEPTS, build_prompt
from config import load_config
from generator import ASPECTS, ImageGenerator, prepare_input, to_jpeg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("product_bot")

config = load_config()
generator = ImageGenerator(config.openai_api_key, config.image_model, config.image_quality)
router = Router()
busy: set[int] = set()


class Flow(StatesGroup):
    custom_scene = State()
    infographic_text = State()


# ---------- доступ только для своих ----------

@router.message.outer_middleware()
@router.callback_query.outer_middleware()
async def only_allowed(handler, event: TelegramObject, data: dict):
    user = data.get("event_from_user")
    if not config.allowed_user_ids:
        if isinstance(event, Message):
            await event.answer(
                f"Ваш Telegram ID: <code>{user.id}</code>\n"
                "Впишите его в ALLOWED_USER_IDS в файле .env и перезапустите бота."
            )
        return None
    if user is None or user.id not in config.allowed_user_ids:
        return None  # чужим молча не отвечаем
    return await handler(event, data)


# ---------- клавиатуры ----------

def concepts_kb(aspect: str):
    kb = InlineKeyboardBuilder()
    for key, (title, _) in CONCEPTS.items():
        kb.button(text=title, callback_data=f"c:{key}")
    kb.button(text="✍️ Свой сценарий", callback_data="custom")
    kb.adjust(2)
    nxt = list(ASPECTS)[(list(ASPECTS).index(aspect) + 1) % len(ASPECTS)]
    kb.row(InlineKeyboardButton(text=f"Формат: {aspect}  →  {nxt}", callback_data=f"a:{nxt}"))
    return kb.as_markup()


def result_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Ещё вариант", callback_data="again")
    kb.button(text="🎨 Другой концепт", callback_data="concepts")
    kb.button(text="🅰️ Инфографика (точный текст)", callback_data="info:tpl")
    kb.button(text="✨ Инфографика (ИИ-дизайн)", callback_data="info:ai")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


# ---------- вспомогательное ----------

async def download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


async def send_result(message: Message, state: FSMContext, img: Image.Image, caption: str,
                      clean: bool = True) -> None:
    data = to_jpeg(img)
    await message.answer_photo(BufferedInputFile(data, "card.jpg"), caption=caption)
    doc = await message.answer_document(
        BufferedInputFile(data, "card.jpg"), caption="Файл в полном качестве", reply_markup=result_kb()
    )
    if clean:  # инфографику всегда кладём на последнее «чистое» фото, без текста
        await state.update_data(result_id=doc.document.file_id)


async def run_generation(message: Message, state: FSMContext, user_id: int, prompt: str, caption: str,
                         source_key: str = "src_id", clean: bool = True) -> None:
    data = await state.get_data()
    file_id = data.get(source_key)
    if not file_id:
        await message.answer("Сначала пришлите фото товара 📷")
        return
    if user_id in busy:
        await message.answer("⏳ Уже генерирую, подождите…")
        return
    busy.add(user_id)
    aspect = data.get("aspect", "3:4")
    status = await message.answer("⏳ Генерирую, обычно это 30–90 секунд…")
    try:
        async with ChatActionSender.upload_photo(bot=message.bot, chat_id=message.chat.id):
            raw = prepare_input(await download(message.bot, file_id))
            img = await generator.edit(raw, prompt, aspect)
        await send_result(message, state, img, caption, clean)
    except OpenAIError as e:
        log.exception("OpenAI error")
        await message.answer(f"❌ Ошибка OpenAI: {e}")
    except Exception as e:  # noqa: BLE001 — бот личный, показываем причину сразу
        log.exception("Generation failed")
        await message.answer(f"❌ Не получилось: {e}")
    finally:
        busy.discard(user_id)
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass


# ---------- команды и фото ----------

@router.message(CommandStart())
@router.message(Command("help"))
async def start(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer(
        "👋 Пришлите фото товара (можно с телефона, лучше <b>файлом</b> — так качество выше).\n\n"
        "Дальше выберите концепт — получите профессиональную карточку для маркетплейса. "
        "Потом можно добавить инфографику с вашим текстом."
    )


@router.message(F.photo)
@router.message(F.document.mime_type.startswith("image/"))
async def got_photo(message: Message, state: FSMContext) -> None:
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    data = await state.get_data()
    aspect = data.get("aspect", "3:4")
    await state.set_state(None)
    await state.update_data(src_id=file_id, aspect=aspect, result_id=None)
    await message.answer("Выберите концепт съёмки:", reply_markup=concepts_kb(aspect))


# ---------- выбор концепта ----------

@router.callback_query(F.data.startswith("a:"))
async def toggle_aspect(call: CallbackQuery, state: FSMContext) -> None:
    aspect = call.data[2:]
    await state.update_data(aspect=aspect)
    await call.message.edit_reply_markup(reply_markup=concepts_kb(aspect))
    await call.answer(f"Формат {aspect}")


@router.callback_query(F.data == "concepts")
async def show_concepts(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await call.message.answer("Выберите концепт съёмки:", reply_markup=concepts_kb(data.get("aspect", "3:4")))
    await call.answer()


@router.callback_query(F.data.startswith("c:"))
async def pick_concept(call: CallbackQuery, state: FSMContext) -> None:
    key = call.data[2:]
    if key not in CONCEPTS:
        await call.answer("Неизвестный концепт")
        return
    prompt = build_prompt(key)
    await state.update_data(prompt=prompt, caption=CONCEPTS[key][0])
    await call.answer()
    await run_generation(call.message, state, call.from_user.id, prompt, CONCEPTS[key][0])


@router.callback_query(F.data == "custom")
async def ask_custom(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.custom_scene)
    await call.message.answer(
        "Опишите сцену своими словами, например:\n"
        "<i>на мраморной столешнице в ванной, рядом полотенце и свеча, утренний свет</i>"
    )
    await call.answer()


@router.message(Flow.custom_scene, F.text)
async def got_custom(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    prompt = build_prompt(None, custom_scene=message.text)
    await state.update_data(prompt=prompt, caption="✍️ Свой сценарий")
    await run_generation(message, state, message.from_user.id, prompt, "✍️ Свой сценарий")


@router.callback_query(F.data == "again")
async def again(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await call.answer()
    if not data.get("prompt"):
        await call.message.answer("Сначала выберите концепт.")
        return
    await run_generation(call.message, state, call.from_user.id, data["prompt"], data.get("caption", ""))


# ---------- инфографика ----------

@router.callback_query(F.data.startswith("info:"))
async def ask_infographic(call: CallbackQuery, state: FSMContext) -> None:
    mode = call.data.split(":", 1)[1]
    await state.set_state(Flow.infographic_text)
    await state.update_data(info_mode=mode, info_base=(await state.get_data()).get("result_id"))
    await call.message.answer(
        "Пришлите текст для карточки. <b>Первая строка — заголовок</b>, остальные — преимущества "
        f"(до {infographic.MAX_FEATURES}), например:\n\n"
        "<code>Платье из льна\n100% натуральный лён\nНе мнётся\nРазмеры 42–54</code>"
    )
    await call.answer()


@router.message(Flow.infographic_text, F.text)
async def got_infographic(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    title, features = infographic.parse_text(message.text)
    if not data.get("info_base"):
        await message.answer("Нет готовой картинки — сначала сгенерируйте фото товара.")
        return

    if data.get("info_mode") == "ai":
        prompt = AI_INFOGRAPHIC_PROMPT.format(
            title=title, features="\n".join(f"- {f}" for f in features) or "-"
        )
        await run_generation(message, state, message.from_user.id, prompt, "✨ Инфографика (ИИ)",
                             source_key="info_base", clean=False)
        return

    raw = await download(message.bot, data["info_base"])
    img = await asyncio.to_thread(
        infographic.render, Image.open(io.BytesIO(raw)), message.text, config.font_path
    )
    await send_result(message, state, img, "🅰️ Инфографика", clean=False)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Пришлите фото товара 📷 или /help")


async def main() -> None:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    log.info("Бот запущен. Модель: %s, качество: %s", config.image_model, config.image_quality)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
