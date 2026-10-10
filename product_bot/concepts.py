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

AI_INFOGRAPHIC_PROMPT = (
    "Turn this product photo into a professional marketplace product card with infographics. "
    "Keep the product and the scene exactly as they are. Add a clean, modern infographic layout: "
    "a bold headline, and the features as neat callouts/badges with simple icons placed so they do not cover the product. "
    "Use EXACTLY this text, spelled character by character, in the same language, without adding other words:\n"
    "Headline: {title}\n"
    "Features:\n{features}"
)

EDIT_PROMPT = (
    "Edit this product photo according to the request below. Change only what is asked; keep the product itself "
    "exactly the same (shape, colors, materials, logos, labels, printed text) unless the request is explicitly "
    "about the product, and keep the rest of the composition, lighting and quality.\n"
    "Request: {request}"
)


def build_prompt(concept_key: str | None, custom_scene: str | None = None) -> str:
    scene = custom_scene if custom_scene else CONCEPTS[concept_key][1]
    return BASE_PROMPT.format(scene=scene)
