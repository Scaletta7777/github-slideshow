"""Инфографика по шаблону: текст рисуется программно, поэтому всегда без ошибок (в т.ч. кириллица)."""

import colorsys
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BOLD_FONTS = [
    "fonts/Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]
REGULAR_FONTS = [
    "fonts/Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]

DARK = (28, 28, 34)
MAX_FEATURES = 6


def _find_font(candidates: list[str], override: str | None) -> str | None:
    for path in ([override] if override else []) + candidates:
        if path and os.path.exists(path):
            return path
    return None


def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def parse_text(text: str) -> tuple[str, list[str]]:
    lines = [ln.strip().lstrip("-•*—–✓✔ ").strip() for ln in text.strip().splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return "", []
    return lines[0], lines[1 : 1 + MAX_FEATURES]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _accent_color(img: Image.Image) -> tuple[int, int, int]:
    """Самый насыщенный из основных цветов фото — чтобы акцент сочетался с картинкой."""
    small = img.convert("RGB").resize((96, 96))
    palette = small.quantize(colors=8).convert("RGB").getcolors(96 * 96) or []
    best, best_score = (230, 70, 90), 0.0
    for count, (r, g, b) in palette:
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        score = s * (1 - abs(l - 0.5) * 2) * (count ** 0.3)
        if score > best_score and 0.25 < l < 0.7 and s > 0.35:
            best, best_score = (r, g, b), score
    # приводим к читаемому насыщенному тону
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in best))
    r, g, b = colorsys.hls_to_rgb(h, min(max(l, 0.38), 0.5), max(s, 0.6))
    return round(r * 255), round(g * 255), round(b * 255)


def _panel(base: Image.Image, box: tuple[int, int, int, int], radius: int, fill, shadow: bool = True) -> None:
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
        off = max(2, radius // 4)
        ImageDraw.Draw(sh).rounded_rectangle(
            (box[0], box[1] + off, box[2], box[3] + off), radius, fill=(0, 0, 0, 70)
        )
        base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(radius // 2 + 2)))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=fill)
    base.alpha_composite(layer)


def render(img: Image.Image, text: str, font_override: str | None = None) -> Image.Image:
    title, features = parse_text(text)
    base = img.convert("RGBA")
    W, H = base.size
    unit = W / 100  # все размеры — в процентах от ширины
    margin = round(4 * unit)
    accent = _accent_color(img)
    bold_path = _find_font(BOLD_FONTS, font_override)
    regular_path = _find_font(REGULAR_FONTS, font_override) or bold_path
    draw = ImageDraw.Draw(base)

    # --- Заголовок: плашка сверху слева, шрифт уменьшается, пока не влезет в 3 строки ---
    if title:
        max_w = round(W * 0.86) - margin * 2
        size = round(7 * unit)
        while True:
            font = _font(bold_path, size)
            lines = _wrap(draw, title.upper(), font, max_w)
            if len(lines) <= 3 or size <= 3 * unit:
                break
            size -= 2
        line_h = round(size * 1.18)
        text_w = max(draw.textlength(ln, font=font) for ln in lines)
        pad = round(2.6 * unit)
        box = (margin, margin, margin + round(text_w) + pad * 2, margin + line_h * len(lines) + pad * 2 - (line_h - size))
        _panel(base, box, round(2.5 * unit), (255, 255, 255, 238))
        # акцентная полоса слева
        ImageDraw.Draw(base).rounded_rectangle(
            (box[0], box[1], box[0] + round(1.1 * unit), box[3]), round(0.55 * unit), fill=accent + (255,)
        )
        draw = ImageDraw.Draw(base)
        y = box[1] + pad
        for ln in lines:
            draw.text((box[0] + pad + round(0.4 * unit), y), ln, font=font, fill=DARK)
            y += line_h

    # --- Преимущества: «таблетки» с галочкой снизу слева ---
    if features:
        size = round(3.6 * unit)
        font = _font(regular_path, size)
        mark_font = _font(bold_path, round(size * 0.95))
        pad_x, pad_y = round(2 * unit), round(1.4 * unit)
        circle = round(size * 1.5)
        max_w = round(W * 0.62) - circle - pad_x * 3
        gap = round(1.6 * unit)
        items = [_wrap(draw, f, font, max_w)[:2] for f in features]
        line_h = round(size * 1.25)
        heights = [max(circle, line_h * len(lines) - (line_h - size)) + pad_y * 2 for lines in items]
        y = H - margin - sum(heights) - gap * (len(items) - 1)
        for lines, h in zip(items, heights):
            text_w = max(draw.textlength(ln, font=font) for ln in lines)
            box = (margin, y, margin + pad_x * 3 + circle + round(text_w), y + h)
            _panel(base, box, h // 2 if len(lines) == 1 else round(2.5 * unit), (255, 255, 255, 235))
            draw = ImageDraw.Draw(base)
            cx, cy = margin + pad_x, y + (h - circle) // 2
            draw.ellipse((cx, cy, cx + circle, cy + circle), fill=accent + (255,))
            draw.text((cx + circle / 2, cy + circle / 2), "✓", font=mark_font, fill="white", anchor="mm")
            ty = y + (h - (line_h * len(lines) - (line_h - size))) // 2
            for ln in lines:
                draw.text((cx + circle + pad_x, ty), ln, font=font, fill=DARK)
                ty += line_h
            y += h + gap

    return base.convert("RGB")
