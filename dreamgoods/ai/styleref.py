"""Референс оформления: разбор стиля по фото-примеру и встраивание в промпт кадра.

Пример оформления — это ТОЛЬКО стиль: свет, цветовая гамма, фон и обстановка, композиция, настроение, обработка.
Из него нельзя брать предметы, товары, людей, текст и логотипы — это прямо сказано генератору.
Обложка (главное фото) референсом не меняется: там действуют правила площадки.
"""
from .images import jpeg_data_url
from .polza import chat

# блоки кадров, к которым референс применяется по умолчанию (обложка — никогда)
DEFAULT_BLOCKS = ["detail", "usage", "scene", "lifestyle"]
BLOCKS_RU = {"studio": "на белом фоне (кроме обложки)", "detail": "детали крупно", "usage": "на человеке крупно",
             "scene": "в полный рост / общий план", "lifestyle": "лайфстайл"}

DESCRIBE_PROMPT = """You are an art director. You get 1-3 example photos that show the VISUAL STYLE a brand wants for its product
photos, and the client's note (in Russian) about what they like in them. Write a precise style brief for an image generator.
Describe ONLY the style, not the objects: lighting (direction, softness, color temperature, time of day), color palette and
grading, background and setting type, composition and framing, depth of field and camera feel, mood, post-processing look.
Follow the client's note: focus on what they want to take; if they say to ignore something (e.g. the background), leave it out.
Do not mention specific products, people, brands or text from the photos.
If the photos clearly show content prohibited by Russian law (LGBT rainbow pride flag or LGBT symbols, Nazi symbols, terrorist
symbols, drug symbols, nudity), describe it in Russian in "prohibited"; otherwise leave it empty. Never invent it.
Reply with ONLY JSON: {"description": "<English, 50-90 words>", "name_ru": "<short Russian name, 1-3 words>", "prohibited": ""}"""


def describe(st, images, note, trace):
    """Разбор стиля по фото. Возвращает (описание англ., имя рус., стоимость)."""
    content = [{"type": "text", "text": f"Client's note: {note or '—'}\nExample photos:"}]
    for data in images[:3]:
        content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(data, 1024)}})
    res, cost, _ = chat(st, st.get("profile_model") or st.get("qc_model"), DESCRIBE_PROMPT, content, trace,
                        "оформление", 800, "none")
    return (str(res.get("description") or "").strip(), str(res.get("name_ru") or "").strip(), cost,
            str(res.get("prohibited") or "").strip())


def applies(block, blocks, is_cover):
    """Применять ли референс к кадру этого блока."""
    # оформление применяется к одним и тем же видам кадров (детали, на человеке, общий план, лайфстайл);
    # кадры «на белом фоне» и обложка остаются по правилам площадки. Выбор блоков в интерфейсе убран.
    return not is_cover and block in DEFAULT_BLOCKS


def apply(prompt, n_product, n_persona, count, description, note=""):
    """Пояснение для генератора: фото после фото товара (и модели) — пример оформления."""
    if not count:
        return prompt
    start = n_product + n_persona + 1
    nums = f"photo {start}" if count == 1 else f"photos {start}-{start + count - 1}"
    style = description.strip().rstrip(".") if description else "as in the example"
    head = "" if n_persona else f"The first {n_product} attached photo(s) show the product. "
    intro = (head + f"Attached {nums}: a STYLE reference only. Match its visual style — {style}. "
             + (f"Client's wish: {note.strip().rstrip('.')}. " if note.strip() else "")
             + "Do NOT copy any product, object, person, text or logo from the style reference; the product must stay "
               "exactly as in the product photos. ")
    return intro + prompt


def profile_hint(description, note):
    """Подсказка для профиля товара: подобрать локации и настроение под оформление."""
    return (description.strip().rstrip(".") + (f" (client: {note.strip()})" if note.strip() else "")) if description else ""
