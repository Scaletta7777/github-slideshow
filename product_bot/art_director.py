"""ИИ-арт-директор: смотрит на фото товара и решает, какой дизайн карточки продаст его лучше всего."""

import base64

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from concepts import INFO_STYLES


class CardPlan(BaseModel):
    style_key: str = Field(description="ключ выбранного стиля из списка или 'custom'")
    style_name: str = Field(description="короткое название дизайна по-русски, 1-3 слова")
    design_brief: str = Field(description="конкретное ТЗ дизайнеру на английском")
    headline: str
    subtitle: str
    callouts: list[str]


class Plans(BaseModel):
    product: str = Field(description="что за товар, по-русски")
    plans: list[CardPlan]


class StyleDescription(BaseModel):
    name: str = Field(description="короткое название стиля по-русски, 1-3 слова")
    description: str = Field(description="описание дизайна на английском")


PLAN_INSTRUCTIONS = """You are the art director of a studio that makes top-selling marketplace product cards \
(Wildberries, Ozon, Amazon). Study the product photo: what the product is, its category, target buyer, price \
segment and mood. Then propose {count} clearly DIFFERENT product-card designs that would sell this product best.

For each design choose style_key from the available styles below (or "custom" for your own idea) and write \
design_brief: a concrete brief for the designer, in English, 60-120 words, covering
- layout: where the headline, subtitle and callouts go, how the product is placed and how much empty space;
- typography: font character (serif / geometric sans / condensed…), weight, case, relative sizes;
- color palette: 2-4 colors as hex, taken from the photo or complementing it;
- graphic elements: badges, pills, thin leader lines, icons (style and size), dividers;
- background treatment: keep, simplify, extend, recolor.
Design the way the best Wildberries/Ozon sellers and Aidentika do: few words, big confident headline, \
strong hierarchy, premium look, everything readable on a phone screen.

Available styles:
{styles}

{copy}"""

AUTO_COPY = """Write the copy in {language}: headline of 1-3 words naming the product (or its key benefit), \
subtitle up to 5 words (may be empty), 2-3 callouts of 2-4 words each. Only claim what is plausible from the \
photo. Each design may have different copy."""

USER_COPY = """The seller provided this text; copy it exactly into every design (headline = first line, \
callouts = the rest, subtitle empty) and design around it:
{text}"""

DESCRIBE_INSTRUCTIONS = """This image is a product card the seller likes. Describe its DESIGN so that another \
designer can reproduce the same style for a different product: layout, typography (font character, weight, \
case, sizes), color palette (hex), graphic elements (badges, lines, icons), background treatment, overall mood. \
Ignore the specific product and the specific words. 60-120 words, in English."""


def _image_input(jpeg: bytes) -> dict:
    return {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
        "detail": "high",
    }


class ArtDirector:
    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def plan(self, product_jpeg: bytes, count: int, language: str,
                   user_text: str | None, references: list[dict]) -> Plans:
        styles = [f"- {key}: {desc}" for key, (_, desc) in INFO_STYLES.items()]
        styles += [f"- {r['id']}: (seller's favourite reference) {r['description']}" for r in references]
        copy = USER_COPY.format(text=user_text) if user_text else AUTO_COPY.format(language=language)
        instructions = PLAN_INSTRUCTIONS.format(count=count, styles="\n".join(styles), copy=copy)
        resp = await self.client.responses.parse(
            model=self.model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": instructions},
                                                _image_input(product_jpeg)]}],
            text_format=Plans,
        )
        result = resp.output_parsed
        if not result or not result.plans:
            raise RuntimeError("арт-директор не предложил ни одного дизайна")
        result.plans = result.plans[:count]
        return result

    async def describe(self, card_jpeg: bytes) -> StyleDescription:
        resp = await self.client.responses.parse(
            model=self.model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": DESCRIBE_INSTRUCTIONS},
                                                _image_input(card_jpeg)]}],
            text_format=StyleDescription,
        )
        return resp.output_parsed
