"""Концепты (сценарии) съёмки. Добавляйте свои — бот подхватит их автоматически."""

CONCEPTS: dict[str, tuple[str, str]] = {
    # key: (название на кнопке, описание сцены для модели)
    "studio": (
        "📸 Каталог (белый фон)",
        "clean catalog shot on a pure white seamless background, soft even studio lighting, "
        "subtle natural contact shadow under the product, product centered",
    ),
    "color": (
        "🎨 Студия, цветной фон",
        "studio shot on a smooth gradient backdrop in a color that complements the product, "
        "soft key light with gentle shadow, minimalist premium look",
    ),
    "podium": (
        "🔷 Подиум",
        "product standing on an elegant geometric podium (cylinders and cubes) in soft pastel tones, "
        "modern 3D-like studio scene, soft shadows",
    ),
    "interior": (
        "🛋 Интерьер",
        "lifestyle photo of the product in a cozy, modern, tastefully styled home interior that fits "
        "how the product is used, natural window light, shallow depth of field",
    ),
    "model": (
        "🧍 На модели / в руках",
        "the product worn or held by an attractive professional model in a natural pose, "
        "fashion e-commerce photography, clean background, the product is the clear focus",
    ),
    "flatlay": (
        "🗂 Раскладка (flat lay)",
        "top-down flat lay composition with a few tasteful props that match the product's theme, "
        "neat arrangement, soft diffused light",
    ),
    "nature": (
        "🌿 На природе",
        "outdoor scene with natural sunlight that suits the product (stones, leaves, wood, water or sand), "
        "fresh and airy mood, product in sharp focus",
    ),
    "luxury": (
        "✨ Премиум (тёмный)",
        "luxury advertising shot on a dark background with dramatic rim lighting, glossy reflections, "
        "rich deep tones, high-end commercial look",
    ),
}

BASE_PROMPT = (
    "You are a professional e-commerce product photographer and retoucher. "
    "Use the product from the input image EXACTLY as it is: preserve its shape, proportions, colors, "
    "materials, textures, logos, labels and any printed text. Do not redesign, replace or add parts to the product. "
    "Remove the original background and surroundings. "
    "Create a photorealistic, high-resolution marketplace product photo: {scene}. "
    "Sharp focus on the product, accurate colors, commercial quality, the whole product visible with some "
    "free space around it. Do not add any text, captions, watermarks or logos that are not on the product."
)

# Стили ИИ-инфографики: (название на кнопке, описание дизайна для модели)
INFO_STYLES: dict[str, tuple[str, str]] = {
    "minimal": (
        "◻️ Минимализм",
        "minimal premium style like Apple product pages: one large clean bold sans-serif headline centered "
        "at the top, a small light subtitle under it, lots of empty space, no boxes or panels",
    ),
    "editorial": (
        "🖋 Элегантный",
        "elegant editorial style: a refined serif headline, thin hairline leader lines with tiny captions "
        "pointing to real details of the product, muted natural palette, airy composition",
    ),
    "bold": (
        "🅱️ Журнальный",
        "bold fashion-magazine cover style: a huge heavy condensed uppercase headline across the top, "
        "a short punchy tagline, and a vertical list of small thin-line icons with short uppercase captions",
    ),
    "badges": (
        "🏷 Яркие бейджи",
        "friendly marketplace style: rounded pill-shaped badges in soft bright colors matching the photo, "
        "each with a simple white icon and short text, placed in the corners, rounded modern font",
    ),
}

INFOGRAPHIC_PROMPT = (
    "You are a top marketplace product-card designer. Turn this product photo into a high-converting, "
    "magazine-quality main gallery image for a marketplace (Wildberries, Ozon, Amazon).\n"
    "PRODUCT: keep the product itself IDENTICAL: the same shape, proportions, colors, materials, textures, "
    "logos, labels and printed text. Do not redraw, restyle or replace it.\n"
    "LAYOUT: you may recompose, extend or simplify the background and move or scale the product to free clean "
    "space for typography; text must never overlap the product. The photo stays realistic and high-end.\n"
    "DESIGN STYLE: {style}.\n"
    "TYPOGRAPHY: one dominant headline (very large, 1-4 words), an optional short subtitle, and at most "
    "2-4 short feature callouts. Strong visual hierarchy, generous margins, precise alignment, crisp perfectly "
    "legible text, a cohesive color palette taken from the photo, consistent thin-line icons. No clutter, "
    "no extra words, no prices, no watermarks, no invented brand logos.\n"
    "{text}"
)

USER_TEXT = (
    "TEXT: use EXACTLY this text, spelled character by character, in the language it is written in, "
    "without adding other words. Shorten nothing.\nHeadline: {title}\n{features}"
)

AUTO_TEXT = (
    "TEXT: write the copy yourself in {language}: a catchy headline of 1-3 words that names the product, "
    "an optional subtitle of up to 5 words, and 2-3 benefit callouts of 2-4 words each. Only claim what is "
    "plausible from the photo. Spell everything correctly."
)


def build_infographic_prompt(style_key: str, title: str | None, features: list[str], language: str) -> str:
    if title:
        lines = "\n".join(f"- {f}" for f in features)
        text = USER_TEXT.format(title=title, features=f"Features:\n{lines}" if lines else "")
    else:
        text = AUTO_TEXT.format(language=language)
    return INFOGRAPHIC_PROMPT.format(style=INFO_STYLES[style_key][1], text=text)

EDIT_PROMPT = (
    "Edit this product photo according to the request below. Change only what is asked; keep the product itself "
    "exactly the same (shape, colors, materials, logos, labels, printed text) unless the request is explicitly "
    "about the product, and keep the rest of the composition, lighting and quality.\n"
    "Request: {request}"
)


def build_prompt(concept_key: str | None, custom_scene: str | None = None) -> str:
    scene = custom_scene if custom_scene else CONCEPTS[concept_key][1]
    return BASE_PROMPT.format(scene=scene)
