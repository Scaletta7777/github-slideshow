"""Telegram-бот: фото товара -> профессиональная карточка для маркетплейса (OpenAI Images API)."""

import asyncio
import html
import io
import logging
import os
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramNetworkError, TelegramNotFound, TelegramUnauthorizedError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Update
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InputMediaPhoto,
    Message,
    TelegramObject,
)
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder
from openai import OpenAIError
from PIL import Image

import infographic
import access
import style_library
import updater
from art_director import ArtDirector
from concepts import (
    SERIES_SLIDE_PROMPT,
    AUTO_TEXT,
    CONCEPTS,
    EDIT_PROMPT,
    INFO_STYLES,
    REFERENCE_AUTO_TEXT,
    REFERENCE_CARD_PROMPT,
    build_infographic_prompt,
    build_prompt,
    exact_text,
)
from config import load_config
from generator import ASPECTS, ImageGenerator, prepare_input, to_jpeg, to_preview_jpeg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("product_bot")

config = load_config()
generator = ImageGenerator(config.openai_api_key, config.image_model, config.image_quality)
director = ArtDirector(generator.client, config.text_model)
router = Router()
dp = Dispatcher()
restart_request: dict = {}  # {"chat": id, "offset": update_id + 1} — выставляется /restart и /update
busy: set[int] = set()


class Flow(StatesGroup):
    custom_scene = State()
    infographic_text = State()
    edit_text = State()
    series_info = State()
    add_style = State()
    ref_card = State()
    ref_product = State()


VARIANT_CHOICES = (1, 2, 4, 8)
SERIES_CHOICES = (3, 5, 7)  # сколько слайдов добавить к обложке
MAX_PARALLEL = 3  # одновременных запросов к OpenAI, чтобы не упереться в лимиты


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


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
    if user is None:
        return None
    if is_admin(user.id) or user.id in access.load():
        return await handler(event, data)
    if isinstance(event, Message):
        await request_access(event, user)
    return None


def is_admin(user_id: int) -> bool:
    """Владельцы — те, чьи ID вписаны в ALLOWED_USER_IDS. Остальных они пускают из Telegram."""
    return user_id in config.allowed_user_ids


access_requests: dict[int, str] = {}  # кто ждёт решения владельца: id -> имя


async def request_access(message: Message, user) -> None:
    name = user.full_name + (f" (@{user.username})" if user.username else "")
    if user.id in access_requests:
        await message.answer("⏳ Запрос уже у владельца бота, подождите его решения.")
        return
    access_requests[user.id] = name
    await message.answer("🔒 Это закрытый бот. Я отправил владельцу запрос на доступ — "
                         "как только он разрешит, я напишу вам.")
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Разрешить", callback_data=f"acc:ok:{user.id}")
    kb.button(text="❌ Отклонить", callback_data=f"acc:no:{user.id}")
    for admin in config.allowed_user_ids:
        try:
            await message.bot.send_message(
                admin, f"👤 <b>{html.escape(name)}</b> (ID <code>{user.id}</code>) просит доступ к боту.\n"
                       "Генерации будут оплачиваться с вашего ключа OpenAI.",
                reply_markup=kb.as_markup())
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отправить запрос доступа владельцу %s", admin)


@router.callback_query(F.data.startswith("acc:"))
async def decide_access(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Только владелец может это сделать")
        return
    _, action, raw_id = call.data.split(":")
    user_id = int(raw_id)
    name = access_requests.pop(user_id, None) or access.load().get(user_id) or str(user_id)
    if action == "ok":
        access.add(user_id, name)
        await call.message.edit_text(f"✅ Доступ выдан: {html.escape(name)}. Отозвать — /users")
        await notify(call.bot, user_id, "✅ Владелец открыл вам доступ! Пришлите фото товара — начнём. "
                                        "Подсказка: /start")
    elif action == "no":
        await call.message.edit_text(f"❌ Запрос отклонён: {html.escape(name)}")
        await notify(call.bot, user_id, "❌ Владелец отклонил запрос на доступ.")
    elif action == "rm":
        access.remove(user_id)
        await call.message.edit_text(f"🚫 Доступ отозван: {html.escape(name)}")
        await notify(call.bot, user_id, "🚫 Владелец закрыл вам доступ к боту.")
    await call.answer()


async def notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:  # noqa: BLE001
        log.warning("Не удалось написать пользователю %s", user_id)


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    users = access.load()
    if not users:
        await message.answer("Кроме вас, доступа ни у кого нет. Новый человек просто пишет боту, "
                             "и вам приходит запрос с кнопкой «Разрешить».")
        return
    for user_id, name in users.items():
        kb = InlineKeyboardBuilder()
        kb.button(text="🚫 Отозвать доступ", callback_data=f"acc:rm:{user_id}")
        await message.answer(f"👤 {html.escape(name)} — ID <code>{user_id}</code>", reply_markup=kb.as_markup())


# ---------- клавиатуры ----------

def _next(options, current):
    options = list(options)
    return options[(options.index(current) + 1) % len(options)] if current in options else options[0]


def concepts_kb(aspect: str, variants: int):
    kb = InlineKeyboardBuilder()
    for key, (title, _) in CONCEPTS.items():
        kb.button(text=title, callback_data=f"c:{key}")
    kb.button(text="✍️ Свой сценарий", callback_data="custom")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(text=f"📐 Формат: {aspect}", callback_data=f"a:{_next(ASPECTS, aspect)}"),
        InlineKeyboardButton(text=f"🔢 Вариантов: {variants}", callback_data=f"v:{_next(VARIANT_CHOICES, variants)}"),
    )
    return kb.as_markup()


def result_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Доработать", callback_data="edit")
    kb.button(text="🔁 Ещё вариант", callback_data="again")
    kb.button(text="🅰️ Инфографика (точный текст)", callback_data="info:tpl")
    kb.button(text="✨ Инфографика (ИИ-дизайн)", callback_data="info:ai")
    kb.button(text="📚 Серия слайдов (до 8 фото)", callback_data="series")
    kb.button(text="🎨 Другой концепт", callback_data="concepts")
    kb.adjust(2, 1, 1, 1, 1)
    return kb.as_markup()


def info_styles_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 ИИ подберёт стиль", callback_data="is:auto1")
    kb.button(text="🤖 ИИ: 3 варианта", callback_data="is:auto3")
    for key, (title, _) in INFO_STYLES.items():
        kb.button(text=title, callback_data=f"is:{key}")
    refs = style_library.load()
    for ref in refs:
        kb.button(text=f"📌 {ref['name']}", callback_data=f"is:{ref['id']}")
    kb.adjust(2, 2, 2, *([2] * ((len(refs) + 1) // 2)))
    return kb.as_markup()


def auto_text_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Придумай текст сам", callback_data="it:auto")
    return kb.as_markup()


# ---------- вспомогательное ----------

OUTPUT_DIR = Path(__file__).parent / "output"
SEND_TIMEOUT = 180  # секунд на запрос к Telegram (отправка больших файлов)
RETRY_DELAY = 3
last_results: dict[int, tuple[list[bytes], str, int]] = {}  # chat_id -> (файлы, подпись, first_slide) для /resend


async def tg_retry(make_call, tries: int = 3):
    """Повторяет запрос к Telegram при сетевых сбоях (таймаут, обрыв связи)."""
    for attempt in range(1, tries + 1):
        try:
            return await make_call()
        except TelegramNetworkError:
            if attempt == tries:
                raise
            log.warning("Telegram network error, retry %d/%d", attempt, tries - 1)
            await asyncio.sleep(RETRY_DELAY * attempt)


async def download(bot: Bot, file_id: str) -> bytes:
    async def call() -> bytes:
        buf = io.BytesIO()
        await bot.download(file_id, destination=buf, timeout=120)
        return buf.getvalue()
    return await tg_retry(call)


def save_outputs(files: list[bytes]) -> Path:
    """Каждая готовая картинка сохраняется на диск — за неё уже заплачено, терять нельзя."""
    folder = OUTPUT_DIR / time.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    for i, f in enumerate(files, 1):
        (folder / f"{stamp}_{i}.jpg").write_bytes(f)
    return folder


async def send_files(message: Message, files: list[bytes], caption: str, first_slide: int = 0) -> None:
    """Превью фото + файл в полном качестве с кнопками. Кнопки работают с файлом, к которому прикреплены."""
    if len(files) == 1:
        await tg_retry(lambda: message.answer_photo(
            BufferedInputFile(files[0], "card.jpg"), caption=caption))
    else:
        await tg_retry(lambda: message.answer_media_group([
            InputMediaPhoto(media=BufferedInputFile(f, f"card_{i}.jpg"), caption=caption if i == 1 else None)
            for i, f in enumerate(files, 1)
        ]))
    for i, f in enumerate(files, 1):
        if first_slide:
            label = f"Слайд {first_slide + i - 1} — файл в полном качестве"
        else:
            label = f"Вариант {i} — файл в полном качестве" if len(files) > 1 else "Файл в полном качестве"
        await tg_retry(lambda: message.answer_document(
            BufferedInputFile(f, f"card_{i}.jpg"), caption=label, reply_markup=result_kb()))


async def send_results(message: Message, images: list[Image.Image], caption: str, first_slide: int = 0) -> None:
    files = [to_jpeg(img) for img in images]
    last_results[message.chat.id] = (files, caption, first_slide)
    try:
        save_outputs(files)
    except OSError:
        log.exception("Не удалось сохранить картинки на диск")
    await send_files(message, files, caption, first_slide)


Job = tuple[str, list[bytes]]  # (промпт, картинки-образцы)


async def run_generation(message: Message, state: FSMContext, user_id: int, prompt: str | list[Job],
                         caption: str, file_id: str | None = None, variants: int | None = None,
                         first_slide: int = 0) -> bool:
    """file_id — исходник (по умолчанию загруженное фото товара); variants — сколько картинок сгенерировать.
    Если prompt — список заданий, по каждому генерируется одна картинка (параллельно)."""
    data = await state.get_data()
    file_id = file_id or data.get("src_id")
    variants = len(prompt) if isinstance(prompt, list) else (variants or data.get("variants", 1))
    if not file_id:
        await message.answer("Сначала пришлите фото товара 📷")
        return False
    if user_id in busy:
        await message.answer("⏳ Уже генерирую, подождите…")
        return False
    busy.add(user_id)
    aspect = data.get("aspect", "3:4")
    forms = ("слайд", "слайда", "слайдов") if first_slide else ("вариант", "варианта", "вариантов")
    what = f" {variants} {plural(variants, *forms)}" if variants > 1 else ""
    wait = "обычно это 30–90 секунд" if variants <= 2 else "это займёт 2–5 минут"
    status = await message.answer(f"⏳ Генерирую{what}, {wait}…")
    try:
        async with ChatActionSender.upload_photo(bot=message.bot, chat_id=message.chat.id):
            raw = prepare_input(await download(message.bot, file_id))
            if isinstance(prompt, list):
                sem, done = asyncio.Semaphore(MAX_PARALLEL), 0

                async def one(p: str, refs: list[bytes]) -> list[Image.Image]:
                    nonlocal done
                    async with sem:
                        result = await generator.edit(raw, p, aspect, references=refs)
                    done += 1
                    if len(prompt) > 2:
                        try:
                            await status.edit_text(f"⏳ Готово {done} из {len(prompt)}…")
                        except Exception:  # noqa: BLE001
                            pass
                    return result

                batches = await asyncio.gather(*(one(p, refs) for p, refs in prompt))
                images = [img for batch in batches for img in batch]
            else:
                images = await generator.edit(raw, prompt, aspect, n=variants)
        await send_results(message, images, caption, first_slide)
        return True
    except TelegramNetworkError as e:
        log.exception("Telegram send failed")
        if message.chat.id in last_results:  # картинки готовы и сохранены, не дошла только отправка
            await message.answer(f"⚠️ Картинки готовы, но Telegram не принял файл ({e}). "
                                 "Ничего не потеряно — нажмите /resend, чтобы получить их снова.")
        else:
            await message.answer(f"❌ Нет связи с Telegram: {e}. Попробуйте ещё раз.")
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
    return False


# ---------- команды и фото ----------

@router.message(CommandStart())
@router.message(Command("help"))
async def start(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer(
        "👋 Пришлите фото товара (можно с телефона, лучше <b>файлом</b> — так качество выше).\n\n"
        "Дальше выберите концепт — получите профессиональную карточку для маркетплейса. "
        "Потом можно добавить инфографику с вашим текстом.\n\n"
        "🖼 /ref — прислать референс и фото товара: бот повторит стиль\n"
        "📌 /addstyle — научить бота стилю: пришлите карточку-образец, которая нравится\n"
        "📋 /styles — сохранённые образцы"
        + ("\n\n<b>Для владельца:</b>\n👥 /users — кто имеет доступ\n"
           "⬇️ /update — обновить бота с GitHub\n🔄 /restart — перезапустить бота"
           if is_admin(message.from_user.id) else "")
    )


# ---------- библиотека образцов ----------

@router.message(Command("addstyle"))
async def ask_style_sample(message: Message, state: FSMContext) -> None:
    await state.set_state(Flow.add_style)
    await message.answer(
        "Пришлите карточку-образец, дизайн которой вам нравится (фото или файлом): "
        "с Aidentika, маркетплейса, Pinterest. Бот запомнит стиль и будет делать карточки «как этот»."
    )


@router.message(Flow.add_style, F.photo)
@router.message(Flow.add_style, F.document.mime_type.startswith("image/"))
async def got_style_sample(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    status = await message.answer("🧠 Изучаю дизайн образца…")
    try:
        jpeg = to_preview_jpeg(await download(message.bot, file_id), side=1536)
        desc = await director.describe(jpeg)
        ref = style_library.add(desc.name, desc.description, jpeg)
    except Exception as e:  # noqa: BLE001
        log.exception("Style sample failed")
        await status.edit_text(f"❌ Не получилось: {e}")
        return
    await status.edit_text(
        f"📌 Стиль «{ref['name']}» сохранён. Он появится в выборе стилей инфографики, "
        "а ИИ-арт-директор будет предлагать его, когда он подходит товару.\n"
        "Добавить ещё — /addstyle, список и удаление — /styles"
    )


@router.message(Command("ref"))
async def ask_reference(message: Message, state: FSMContext) -> None:
    await state.set_state(Flow.ref_card)
    await message.answer(
        "🖼 <b>Карточка по референсу</b>\n\n"
        "<b>Шаг 1 из 2.</b> Пришлите референс — карточку, стиль которой нужно повторить "
        "(скриншот с маркетплейса, Aidentika, Pinterest)."
    )


@router.message(Flow.ref_card, F.photo)
@router.message(Flow.ref_card, F.document.mime_type.startswith("image/"))
async def got_reference(message: Message, state: FSMContext) -> None:
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    await state.update_data(ref_file=file_id, ref_notes=None, ref_name=None)
    await state.set_state(Flow.ref_product)
    kb = None
    if (await state.get_data()).get("src_id"):
        b = InlineKeyboardBuilder()
        b.button(text="Взять последнее фото товара", callback_data="ref:last")
        kb = b.as_markup()
    await message.answer("<b>Шаг 2 из 2.</b> Теперь пришлите фото товара (лучше файлом).", reply_markup=kb)


async def _ref_ask_text(message: Message, state: FSMContext, product_file: str) -> None:
    await state.update_data(info_base=product_file, src_id=product_file, info_mode="ai", info_style="oneoff")
    await state.set_state(Flow.infographic_text)
    await message.answer(TEXT_HINT + "\n\nИли пусть бот напишет свой текст в духе референса:",
                         reply_markup=auto_text_kb())


@router.message(Flow.ref_product, F.photo)
@router.message(Flow.ref_product, F.document.mime_type.startswith("image/"))
async def got_ref_product(message: Message, state: FSMContext) -> None:
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    await _ref_ask_text(message, state, file_id)


@router.callback_query(Flow.ref_product, F.data == "ref:last")
async def ref_use_last(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await _ref_ask_text(call.message, state, (await state.get_data())["src_id"])


@router.callback_query(F.data == "save_ref")
async def save_reference(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("ref_file") or not data.get("ref_notes"):
        await call.answer("Референс уже недоступен")
        return
    jpeg = to_preview_jpeg(await download(call.bot, data["ref_file"]), side=1536)
    ref = style_library.add(data.get("ref_name") or "Мой референс", data["ref_notes"], jpeg)
    await call.answer("Сохранено")
    await call.message.edit_text(f"📌 Стиль «{ref['name']}» сохранён — он есть в выборе стилей инфографики.")


# ---------- перезапуск и обновление ----------

async def _schedule_restart(message: Message, event_update: Update) -> None:
    restart_request.update(chat=message.chat.id, offset=event_update.update_id + 1)
    await dp.stop_polling()


@router.message(Command("resend"))
async def cmd_resend(message: Message) -> None:
    if message.chat.id not in last_results:
        await message.answer("Нет последних результатов (они хранятся до перезапуска бота). "
                             "Все картинки также сохраняются на сервере в папке output/.")
        return
    files, caption, first_slide = last_results[message.chat.id]
    try:
        await send_files(message, files, caption, first_slide)
    except TelegramNetworkError as e:
        await message.answer(f"❌ Telegram снова не принял файл: {e}. Попробуйте /resend чуть позже.")


@router.message(Command("restart"))
async def cmd_restart(message: Message, state: FSMContext, event_update: Update) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Перезапуск доступен только владельцу бота.")
        return
    await state.clear()
    await message.answer("🔄 Перезапускаю бота…")
    await _schedule_restart(message, event_update)


@router.message(Command("update"))
async def cmd_update(message: Message, state: FSMContext, event_update: Update) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Обновление доступно только владельцу бота.")
        return
    status = await message.answer("⬇️ Проверяю обновления на GitHub…")
    try:
        changed = await updater.fetch_updates()
        if "requirements.txt" in changed:
            await status.edit_text("📦 Устанавливаю новые библиотеки…")
            await updater.install_requirements()
    except Exception as e:  # noqa: BLE001
        log.exception("Update failed")
        await status.edit_text(f"❌ Не удалось обновиться: {e}")
        return
    if not changed:
        await status.edit_text("✅ У вас уже последняя версия.")
        return
    await status.edit_text("✅ Обновлено: " + ", ".join(changed) + "\n🔄 Перезапускаю бота…")
    await state.clear()
    await _schedule_restart(message, event_update)


@router.message(Command("styles"))
async def list_styles(message: Message) -> None:
    refs = style_library.load()
    if not refs:
        await message.answer("Сохранённых образцов пока нет. Добавьте: /addstyle")
        return
    kb = InlineKeyboardBuilder()
    for ref in refs:
        kb.button(text=f"🗑 {ref['name']}", callback_data=f"rs:{ref['id']}")
    kb.adjust(1)
    await message.answer(
        "Ваши образцы:\n" + "\n".join(f"📌 {r['name']}" for r in refs) + "\n\nНажмите, чтобы удалить:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("rs:"))
async def remove_style(call: CallbackQuery) -> None:
    style_library.remove(call.data[3:])
    await call.answer("Удалено")
    await call.message.delete()


@router.message(F.photo)
@router.message(F.document.mime_type.startswith("image/"))
async def got_photo(message: Message, state: FSMContext) -> None:
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    data = await state.get_data()
    aspect, variants = data.get("aspect", "3:4"), data.get("variants", 1)
    await state.set_state(None)
    await state.update_data(src_id=file_id, aspect=aspect, variants=variants)
    await message.answer("Выберите концепт съёмки:", reply_markup=concepts_kb(aspect, variants))


# ---------- выбор концепта ----------

@router.callback_query(F.data.startswith("a:"))
async def toggle_aspect(call: CallbackQuery, state: FSMContext) -> None:
    aspect = call.data[2:]
    await state.update_data(aspect=aspect)
    data = await state.get_data()
    await call.message.edit_reply_markup(reply_markup=concepts_kb(aspect, data.get("variants", 1)))
    await call.answer(f"Формат {aspect}")


@router.callback_query(F.data.startswith("v:"))
async def toggle_variants(call: CallbackQuery, state: FSMContext) -> None:
    variants = int(call.data[2:])
    await state.update_data(variants=variants)
    data = await state.get_data()
    await call.message.edit_reply_markup(reply_markup=concepts_kb(data.get("aspect", "3:4"), variants))
    await call.answer(f"Вариантов за раз: {variants}")


@router.callback_query(F.data == "concepts")
async def show_concepts(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await call.message.answer(
        "Выберите концепт съёмки:", reply_markup=concepts_kb(data.get("aspect", "3:4"), data.get("variants", 1))
    )
    await call.answer()


@router.callback_query(F.data.startswith("c:"))
async def pick_concept(call: CallbackQuery, state: FSMContext) -> None:
    key = call.data[2:]
    if key not in CONCEPTS:
        await call.answer("Неизвестный концепт")
        return
    prompt = build_prompt(key)
    await state.update_data(prompt=prompt, caption=CONCEPTS[key][0], last_kind="concept")
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
    await state.update_data(prompt=prompt, caption="✍️ Свой сценарий", last_kind="concept")
    await run_generation(message, state, message.from_user.id, prompt, "✍️ Свой сценарий")


@router.callback_query(F.data == "again")
async def again(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await call.answer()
    if data.get("last_kind") == "info":  # повторяем последнюю инфографику / карточку по референсу
        await run_ai_infographic(call.message, state, call.from_user.id,
                                 data.get("last_title"), data.get("last_features", []))
        return
    if not data.get("prompt"):
        await call.message.answer("Сначала выберите концепт.")
        return
    await run_generation(call.message, state, call.from_user.id, data["prompt"], data.get("caption", ""), variants=1)


# ---------- инфографика ----------

@router.callback_query(F.data.startswith("info:"))
async def ask_infographic(call: CallbackQuery, state: FSMContext) -> None:
    mode = call.data.split(":", 1)[1]
    await state.update_data(info_mode=mode, info_base=call.message.document.file_id)
    await call.answer()
    if mode == "ai":
        await state.set_state(None)
        await call.message.answer("Выберите стиль оформления:", reply_markup=info_styles_kb())
        return
    await state.set_state(Flow.infographic_text)
    await call.message.answer(TEXT_HINT)


TEXT_HINT = (
    "Пришлите текст для карточки. <b>Первая строка — заголовок</b>, остальные — преимущества "
    f"(до {infographic.MAX_FEATURES}). Чем короче, тем красивее, например:\n\n"
    "<code>Льняное платье\n100% лён\nНе мнётся\nРазмеры 42–54</code>"
)


@router.callback_query(F.data.startswith("is:"))
async def pick_info_style(call: CallbackQuery, state: FSMContext) -> None:
    style = call.data[3:]
    await state.update_data(info_style=style)
    await state.set_state(Flow.infographic_text)
    await call.answer()
    await call.message.answer(TEXT_HINT + "\n\nИли пусть бот придумает текст сам:", reply_markup=auto_text_kb())


async def run_ai_infographic(message: Message, state: FSMContext, user_id: int,
                             title: str | None, features: list[str]) -> None:
    data = await state.get_data()
    style = data.get("info_style", "auto1")
    text = exact_text(title, features) if title else AUTO_TEXT.format(language=config.card_language)

    await state.update_data(last_kind="info", last_title=title, last_features=features)

    if style == "oneoff":  # /ref: разовый референс
        status = await message.answer("🧠 Изучаю референс…")
        try:
            ref_jpeg = to_preview_jpeg(await download(message.bot, data["ref_file"]), side=1536)
            notes = data.get("ref_notes")
            if not notes:
                desc = await director.describe(ref_jpeg)
                notes = desc.description
                await state.update_data(ref_notes=notes, ref_name=desc.name)
        except Exception as e:  # noqa: BLE001
            log.exception("Reference analysis failed")
            await status.edit_text(f"❌ Не получилось разобрать референс: {e}")
            return
        await status.delete()
        ref_text = text if title else REFERENCE_AUTO_TEXT.format(language=config.card_language)
        prompt = REFERENCE_CARD_PROMPT.format(notes=notes, text=ref_text)
        jobs = [(prompt, [ref_jpeg])] * data.get("variants", 1)
        if not await run_generation(message, state, user_id, jobs, "🖼 По референсу", file_id=data["info_base"]):
            return
        kb = InlineKeyboardBuilder()
        kb.button(text="📌 Запомнить этот стиль", callback_data="save_ref")
        await message.answer("Понравился стиль? Сохраните его, чтобы применять к другим товарам.",
                             reply_markup=kb.as_markup())
        return

    if style in INFO_STYLES:
        jobs = [(build_infographic_prompt(INFO_STYLES[style][1], text), [])]
        caption = "✨ " + INFO_STYLES[style][0]
    elif ref := style_library.get(style):
        jobs = [(build_infographic_prompt(ref["description"], text, with_reference=True),
                 [style_library.image(ref["id"])])]
        caption = f"📌 По образцу «{ref['name']}»"
    else:  # auto1 / auto3 — решает арт-директор
        count = 3 if style == "auto3" else 1
        status = await message.answer("🧠 Арт-директор изучает товар и подбирает дизайн…")
        try:
            preview = to_preview_jpeg(await download(message.bot, data["info_base"]))
            user_text = "\n".join([title, *features]) if title else None
            result = await director.plan(preview, count, config.card_language, user_text, style_library.load())
        except Exception as e:  # noqa: BLE001
            log.exception("Art director failed")
            await status.edit_text(f"❌ Арт-директор не справился: {e}")
            return
        jobs = []
        for plan in result.plans:
            plan_text = text if title else exact_text(plan.headline, plan.callouts, plan.subtitle)
            ref = style_library.get(plan.style_key)
            jobs.append((build_infographic_prompt(plan.design_brief, plan_text, with_reference=bool(ref)),
                         [style_library.image(ref["id"])] if ref else []))
        names = " · ".join(p.style_name for p in result.plans)
        await status.edit_text(f"🧠 Товар: {result.product}\nДизайн: {names}")
        caption = f"🤖 {names}"
    await run_generation(message, state, user_id, jobs, caption, file_id=data["info_base"])


@router.callback_query(F.data == "it:auto")
async def auto_text(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await call.answer()
    if not (await state.get_data()).get("info_base"):
        await call.message.answer("Нет готовой картинки — сначала сгенерируйте фото товара.")
        return
    await run_ai_infographic(call.message, state, call.from_user.id, None, [])


@router.message(Flow.infographic_text, F.text)
async def got_infographic(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    title, features = infographic.parse_text(message.text)
    if not data.get("info_base"):
        await message.answer("Нет готовой картинки — сначала сгенерируйте фото товара.")
        return

    if data.get("info_mode") == "ai":
        await run_ai_infographic(message, state, message.from_user.id, title or None, features)
        return

    raw = await download(message.bot, data["info_base"])
    img = await asyncio.to_thread(
        infographic.render, Image.open(io.BytesIO(raw)), message.text, config.font_path
    )
    await send_results(message, [img], "🅰️ Инфографика")


# ---------- серия слайдов ----------

@router.callback_query(F.data == "series")
async def ask_series_count(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(series_cover=call.message.document.file_id)
    kb = InlineKeyboardBuilder()
    for n in SERIES_CHOICES:
        kb.button(text=f"+{n} → всего {n + 1} фото", callback_data=f"ser:{n}")
    kb.adjust(1)
    await call.answer()
    await call.message.answer(
        "📚 Эта карточка станет обложкой, а бот сделает к ней слайды в том же стиле: преимущества, детали, "
        "товар в использовании, размеры, состав… Сколько слайдов добавить?\n"
        "<i>Каждый слайд — отдельная генерация.</i>",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("ser:"))
async def ask_series_info(call: CallbackQuery, state: FSMContext) -> None:
    arg = call.data[4:]
    await call.answer()
    if arg == "auto":
        await state.set_state(None)
        await run_series(call.message, state, call.from_user.id, None)
        return
    await state.update_data(series_count=int(arg))
    await state.set_state(Flow.series_info)
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Без характеристик, придумай сам", callback_data="ser:auto")
    await call.message.answer(
        "Пришлите характеристики товара одним сообщением: размеры, состав, плотность, комплектация, уход… "
        "Бот возьмёт цифры <b>только</b> отсюда и ничего не выдумает. Например:\n\n"
        "<code>Размер 50×100 и 70×140\n100% хлопок, 500 г/м²\nСтирка при 40°\nЦвета: графит, бежевый, белый</code>",
        reply_markup=kb.as_markup(),
    )


@router.message(Flow.series_info, F.text)
async def got_series_info(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await run_series(message, state, message.from_user.id, message.text)


async def run_series(message: Message, state: FSMContext, user_id: int, info: str | None) -> None:
    data = await state.get_data()
    cover_id = data.get("series_cover")
    product_id = data.get("src_id") or cover_id
    count = data.get("series_count", SERIES_CHOICES[-1])
    if not cover_id:
        await message.answer("Нажмите «📚 Серия слайдов» под готовой карточкой.")
        return
    status = await message.answer(f"🧠 Арт-директор планирует серию из {count} слайдов…")
    try:
        product_jpeg = to_preview_jpeg(await download(message.bot, product_id))
        cover_jpeg = to_preview_jpeg(await download(message.bot, cover_id), side=1536)
        series = await director.plan_series(product_jpeg, cover_jpeg, count, config.card_language, info)
    except Exception as e:  # noqa: BLE001
        log.exception("Series planning failed")
        await status.edit_text(f"❌ Арт-директор не справился: {e}")
        return
    total = len(series.slides)
    await status.edit_text(
        f"🧠 {series.product}. План серии:\n"
        + "\n".join(f"{i}. {s.role}" for i, s in enumerate(series.slides, 2))
    )
    jobs = [
        (SERIES_SLIDE_PROMPT.format(index=i, total=total + 1, role=s.role, scene=s.scene, brief=s.design_brief,
                                    text=exact_text(s.headline, s.callouts, s.subtitle)), [cover_jpeg])
        for i, s in enumerate(series.slides, 2)
    ]
    caption = f"📚 Серия: {', '.join(s.role for s in series.slides)}"
    await run_generation(message, state, user_id, jobs, caption[:1000], file_id=product_id, first_slide=2)


# ---------- доработка текстом ----------

@router.callback_query(F.data == "edit")
async def ask_edit(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.edit_text)
    await state.update_data(edit_base=call.message.document.file_id)
    await call.message.answer(
        "Что изменить? Например:\n"
        "<i>сделай фон светлее</i>, <i>убери тень</i>, <i>добавь веточку эвкалипта слева</i>, "
        "<i>поверни товар чуть боком</i>"
    )
    await call.answer()


@router.message(Flow.edit_text, F.text)
async def got_edit(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    await run_generation(message, state, message.from_user.id, EDIT_PROMPT.format(request=message.text),
                         "✏️ Доработка", file_id=data.get("edit_base"), variants=1)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Пришлите фото товара 📷 или /help")


async def main() -> None:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from aiogram.client.session.aiohttp import AiohttpSession

    bot = Bot(config.bot_token, session=AiohttpSession(timeout=SEND_TIMEOUT),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp.include_router(router)
    try:
        me = await bot.get_me()
    except (TelegramNotFound, TelegramUnauthorizedError):
        await bot.session.close()
        raise SystemExit(
            "Telegram не принял BOT_TOKEN. Проверьте токен в файле .env: "
            "@BotFather → /mybots → ваш бот → API Token."
        )
    except TelegramNetworkError as e:
        await bot.session.close()
        raise SystemExit(f"Нет связи с Telegram, проверьте интернет или VPN. ({e})")
    commands = [
        BotCommand(command="start", description="Начать / помощь"),
        BotCommand(command="ref", description="Карточка по референсу"),
        BotCommand(command="addstyle", description="Добавить образец дизайна"),
        BotCommand(command="styles", description="Мои образцы"),
        BotCommand(command="resend", description="Прислать последние результаты ещё раз"),
    ]
    admin_commands = commands + [
        BotCommand(command="users", description="Кто имеет доступ"),
        BotCommand(command="update", description="Обновить бота"),
        BotCommand(command="restart", description="Перезапустить бота"),
    ]
    await bot.set_my_commands(commands)
    for admin in config.allowed_user_ids:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin))
        except Exception:  # noqa: BLE001
            log.warning("Не удалось задать меню команд для %s", admin)
    log.info("Бот @%s запущен. Модель: %s, качество: %s", me.username, config.image_model, config.image_quality)
    if chat := os.environ.pop("BOT_RESTARTED_CHAT", None):
        try:
            await bot.send_message(int(chat), "✅ Бот перезапущен и готов к работе.")
        except Exception:  # noqa: BLE001
            log.warning("Не удалось отправить сообщение о перезапуске")
    await dp.start_polling(bot)
    if restart_request:
        # подтверждаем команду /restart, иначе Telegram пришлёт её снова и бот уйдёт в цикл перезапусков
        await bot.get_updates(offset=restart_request["offset"], timeout=0)
        await bot.session.close()
        log.info("Перезапуск…")
        updater.restart_process(restart_request["chat"])


if __name__ == "__main__":
    asyncio.run(main())
