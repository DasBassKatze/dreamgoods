"""Серия кадров одного товара как одна фотосессия.

1. Целостность: в каждый кадр добавляется правило серии — тот же свет, баланс белого, цветокоррекция, фон и масштаб
   (студийные кадры); та же модель, образ, причёска, макияж, локация и время суток (кадры с человеком).
2. Опорный кадр: первый кадр группы (обложка для студийных, первый кадр с моделью для съёмки на человеке) снимается
   первым, остальные кадры группы получают его как референс «из той же съёмки» — повторить свет, цвет, фон и образ,
   но не позу и ракурс. Это главное средство целостности: текст держит стиль хуже, чем пример.
3. Эмоции: кадры в полный рост одного товара получают разные эмоции модели (не одно и то же лицо на всех кадрах).

Всё добавляется к промпту при генерации и не хранится в промпте кадра — поэтому обновление не вызывает пересъёмку
уже готовых кадров.
"""
import re
import zlib

from . import prompts as P
from .persona import has_person

# Эмоции для кадров в полный рост: чередуются по порядку кадров, начало списка зависит от артикула
EMOTIONS = [
    "a warm, genuine smile with relaxed eyes",
    "a confident, self-assured look straight into the camera",
    "a light candid laugh, glancing away from the camera",
    "a calm, dreamy gaze into the distance",
    "a playful, slightly flirtatious glance over the shoulder",
    "a cool, serious high-fashion expression",
    "a soft, thoughtful half-smile, looking down",
    "an energetic, joyful expression in mid-movement",
]


def group_of(prompt):
    """studio — товар без людей (белый фон, обложка, детали); person — съёмка на модели; scene — интерьер без людей."""
    b = P.block_of(prompt)
    if b in ("studio", "detail"):
        return "studio"
    if has_person(prompt):
        return "person"
    return "scene"


def is_full_body(prompt):
    return has_person(prompt) and ("full-body" in prompt or "full body" in prompt)


def emotion_for(seed, index):
    start = zlib.crc32(seed.encode()) % len(EMOTIONS)
    return EMOTIONS[(start + index) % len(EMOTIONS)]


def orient(prompt, aspect):
    """«Vertical …» в шаблонах кадров → по формату кадра (для Авито 4:3 — горизонтальный)."""
    try:
        w, h = (int(x) for x in (aspect or "3:4").split(":"))
    except ValueError:
        return prompt
    word = "Vertical" if h > w else "Horizontal" if w > h else "Square"
    return prompt if word == "Vertical" else re.sub(r"\bVertical\b", word, prompt)


SERIES = {
    "studio": ("SERIES CONSISTENCY: this photo is one of a set of photos of this product from a single studio session. "
               "Keep the set uniform: the same background color and tone, the same soft lighting setup and light "
               "direction, the same color temperature and white balance, the same color grading, the same camera height "
               "and the same product scale relative to the frame. Only the angle of the product changes."),
    "person": ("SERIES CONSISTENCY: this photo is one of a set from a single fashion photoshoot. Across the set keep the same "
               "model (face, hairstyle, makeup), the same outfit and accessories, the same location, the same time of day, "
               "the same lighting direction and quality and the same color grading. Only the camera angle, the pose and "
               "the expression change between photos."),
    "scene": ("SERIES CONSISTENCY: this photo is one of a set from a single lifestyle photoshoot: keep the same interior or "
              "location, the same props palette and materials, the same time of day, lighting and color grading across "
              "the set. Only the camera angle and arrangement change."),
}

ANCHOR = {
    "studio": ("Photo {n} is another photo from the same studio session of this product: match its background, lighting, "
               "white balance and color grading exactly. Do NOT copy its camera angle or composition."),
    "person": ("Photo {n} is another photo from the same photoshoot: match its location, lighting, color grading and the "
               "model's outfit, hairstyle and makeup exactly. Do NOT copy its pose, camera angle, framing or expression."),
    "scene": ("Photo {n} is another photo from the same lifestyle photoshoot: match its location, props, lighting and color "
              "grading. Do NOT copy its camera angle or arrangement."),
}


def apply(prompt, aspect, emotion="", anchor_n=0):
    """Правила серии, эмоция и опорный кадр — к промпту кадра перед отправкой генератору."""
    g = group_of(prompt)
    extra = [SERIES[g]]
    if anchor_n:
        extra.append(ANCHOR[g].format(n=anchor_n))
    if emotion:
        extra.append(f"FACIAL EXPRESSION for this photo (overrides any expression mentioned above): {emotion}. "
                     "Each full-body photo of this set shows a different emotion — the face must look natural, alive "
                     "and not like a copy of the other photos.")
    return orient(prompt, aspect) + "\n\n" + " ".join(extra)
