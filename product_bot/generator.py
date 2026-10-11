import base64
import io

from openai import AsyncOpenAI
from PIL import Image, ImageOps

try:  # фото с iPhone (HEIC), если отправлены файлом
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# Формат карточки -> (ширина, высота) итогового изображения
ASPECTS: dict[str, tuple[int, int]] = {
    "3:4": (1200, 1600),  # Wildberries, Ozon, Uzum
    "1:1": (1536, 1536),  # Amazon, Etsy, соцсети
}

MAX_INPUT_SIDE = 2048


def _supports_custom_size(model: str) -> bool:
    return model.startswith("gpt-image-2")


def _supports_input_fidelity(model: str) -> bool:
    return model in ("gpt-image-1", "gpt-image-1.5") or model.startswith("gpt-image-1.5-")


def _request_size(model: str, aspect: str) -> str:
    w, h = ASPECTS[aspect]
    if _supports_custom_size(model):
        return f"{w}x{h}"
    return "1024x1024" if w == h else ("1024x1536" if h > w else "1536x1024")


def prepare_input(raw: bytes) -> bytes:
    """Нормализует фото: поворот по EXIF, RGB, уменьшение до разумного размера, PNG."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    img.thumbnail((MAX_INPUT_SIDE, MAX_INPUT_SIDE))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _fit_aspect(img: Image.Image, aspect: str) -> Image.Image:
    """Обрезает по центру до нужного соотношения (для моделей без произвольного размера)."""
    w, h = ASPECTS[aspect]
    target = w / h
    if abs(img.width / img.height - target) < 0.01:
        return img
    if img.width / img.height > target:  # слишком широкое — режем по бокам
        size = (round(img.height * target), img.height)
    else:  # слишком высокое — режем сверху и снизу
        size = (img.width, round(img.width / target))
    return ImageOps.fit(img, size, method=Image.LANCZOS)


def to_preview_jpeg(raw: bytes, side: int = 1024) -> bytes:
    """Уменьшенная JPEG-копия для анализа текстовой нейросетью."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    img.thumbnail((side, side))
    return to_jpeg(img, quality=88)


def to_jpeg(img: Image.Image, quality: int = 95) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


class ImageGenerator:
    def __init__(self, api_key: str, model: str, quality: str):
        self.client = AsyncOpenAI(api_key=api_key, timeout=300)
        self.model = model
        self.quality = quality

    async def edit(self, image_png: bytes, prompt: str, aspect: str, n: int = 1,
                   references: list[bytes] | None = None) -> list[Image.Image]:
        """references — дополнительные картинки (образцы дизайна), идут после фото товара."""
        extra = {"input_fidelity": "high"} if _supports_input_fidelity(self.model) else {}
        image = ("product.png", image_png, "image/png")
        if references:
            image = [image] + [(f"reference_{i}.jpg", ref, "image/jpeg") for i, ref in enumerate(references, 1)]
        result = await self.client.images.edit(
            model=self.model,
            image=image,
            prompt=prompt,
            size=_request_size(self.model, aspect),
            quality=self.quality,
            output_format="png",
            n=n,
            **extra,
        )
        images = []
        for item in result.data:
            img = Image.open(io.BytesIO(base64.b64decode(item.b64_json)))
            img.load()
            images.append(_fit_aspect(img, aspect))
        return images
