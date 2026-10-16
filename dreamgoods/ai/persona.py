"""Модель клиента (человек на кадрах): «паспорт образа», варианты для примерки, изменение внешности, ракурсы,
описание по фото и встраивание модели в промпт кадра товара.

Паспорт образа (spec) — подробное описание, которое ИИ пишет для каждого варианта ДО генерации картинки:
  appearance — внешность (лицо, волосы, кожа, фигура, возраст) — должна совпадать на всех кадрах;
  style      — стиль: макияж, укладка, стиль одежды, аксессуары, общее настроение, выражение лица и манера позировать;
  look       — наряд и фон для фото-«кастинга» в этом стиле.
Клиент видит только картинки; при выборе варианта его паспорт сохраняется в модели и потом задаёт внешность,
макияж и стиль одежды на всех кадрах товара.
"""
import json
import re

from ..core.logs import log
from .images import jpeg_data_url
from .polza import chat

TAIL = ("Photorealistic, high resolution, natural skin texture, no retouching artifacts. One single photo: no grid, "
        "no collage, no text, no numbers, no labels, no watermarks, no frames.")

STYLE_KEYS = ("makeup", "hair_styling", "clothing_style", "accessories", "vibe", "expression")
STYLE_RU = {"makeup": "Макияж", "hair_styling": "Укладка", "clothing_style": "Стиль одежды", "accessories": "Аксессуары",
            "vibe": "Настроение образа", "expression": "Выражение лица и подача"}

SPEC_RULES = """Rules:
- Follow the client's wishes LITERALLY, including subcultures and bold looks (goth, punk, emo, grunge, y2k, boho, old money,
  streetwear, K-pop, glam, tattoos, piercings, unusual hair colors…). Never "normalize" them to a mainstream look.
  Fill only the details the client did not specify, in the same spirit.
- Adults only (18+). Respectful, non-sexualized wording. No real or famous people.
- appearance: gender, age, skin tone, face shape and notable features, eye color, eyebrows, hair (natural color, length,
  texture, cut), body type and height impression, visible tattoos/piercings/freckles. No clothing here. 40-70 words.
- style: concrete, visual, in English: makeup (exact colors and technique), hair_styling (how the hair is styled),
  clothing_style (what this person wears: garments, colors, materials, silhouettes — used to dress them for product photos),
  accessories (jewelry, nails, glasses…), vibe (overall aesthetic in a few words), expression (facial expression and posing manner).
- look: one specific outfit in that clothing style for a full-body casting photo, and a plain studio background color that
  suits the style.
- name_ru: a short Russian name of the look, 1-3 words (e.g. «Готическая муза»)."""

SPEC_PROMPT = """You are a casting director creating fashion models for product photos of a client's brand.
From the client's wishes (in Russian) create {n} DIFFERENT model variants that all match the wishes but differ in details
(face, hair, makeup nuances), so the client has a real choice.
""" + SPEC_RULES + """
Reply with ONLY JSON: {{"variants": [{{"name_ru": "...", "appearance": "...", "style": {{"makeup": "...", "hair_styling": "...",
"clothing_style": "...", "accessories": "...", "vibe": "...", "expression": "..."}}, "look": {{"outfit": "...", "background": "..."}}}}]}}"""

EDIT_PROMPT = """You are a casting director. Below is the current passport of a fashion model and the client's change request
(in Russian). Produce {n} variant(s) of the UPDATED passport: apply the requested changes exactly and keep everything else
identical (the same person: same face, unless the request concerns the face). If several variants are requested,
vary only how the change is interpreted.
""" + SPEC_RULES + """
Also write "change_en": the change request translated to a precise English instruction for an image editor.
Inside text values never use double quotes (write «...» or single quotes instead).
Reply with ONLY valid JSON: {{"variants": [{{"name_ru": "...", "change_en": "...", "appearance": "...",
"style": {{"makeup": "...", "hair_styling": "...", "clothing_style": "...", "accessories": "...", "vibe": "...", "expression": "..."}},
"look": {{"outfit": "...", "background": "..."}}}}]}}"""

DESCRIBE_PROMPT = """You look at photos of ONE person (a model for product photos) and write their passport for an image generator.
""" + SPEC_RULES + """
Describe what you SEE (do not invent a different style); for clothing_style describe the style the visible outfit suggests.
Reply with ONLY JSON: {"name_ru": "...", "appearance": "...", "style": {"makeup": "...", "hair_styling": "...",
"clothing_style": "...", "accessories": "...", "vibe": "...", "expression": "..."}, "look": {"outfit": "...", "background": "..."}}"""

CANDIDATE = ("Casting photo of a fashion model for a brand. The person: {appearance}. Makeup: {makeup}. Hair styling: {hair}. "
             "Accessories: {acc}. Outfit: {outfit}. Overall aesthetic: {vibe}. Full-body shot from head to feet, facing the camera, "
             "{expression}, face clearly visible and in sharp focus. Plain seamless studio background: {background}; soft even "
             "studio lighting. {tail}")

EDIT = ("The reference photo shows a fashion model. Make a new full-body photo of the SAME person with these changes: {change}. "
        "Everything not mentioned stays exactly the same: face and facial features, body type, age, pose, framing and lighting. "
        "Resulting look — the person: {appearance}. Makeup: {makeup}. Hair styling: {hair}. Accessories: {acc}. Outfit: {outfit}. "
        "Background: {background}. {tail}")

SHEET_VIEWS = {
    "portrait": "close-up portrait from the chest up, facing the camera, face in sharp focus",
    "three-quarter": "full-body shot from head to feet, three-quarter view, relaxed natural pose",
    "side": "full-body shot from head to feet, side profile view, standing straight",
}
SHEET = ("The reference photo shows a fashion model. Make a new photo of EXACTLY the same person: the same face and facial "
         "features, the same hairstyle, hair color and makeup, the same skin tone, age, height impression and body type, "
         "the same outfit, accessories and background as in the reference. Shot: {view}. {tail}")


# ───────── паспорт образа ─────────

def _clean_spec(v):
    """Приводит ответ модели к виду {name_ru, appearance, style{…}, look{outfit, background}, change_en}."""
    v = v if isinstance(v, dict) else {}
    style = v.get("style") if isinstance(v.get("style"), dict) else {}
    look = v.get("look") if isinstance(v.get("look"), dict) else {}
    return {"name_ru": str(v.get("name_ru") or "").strip()[:120],
            "appearance": str(v.get("appearance") or "").strip(),
            "style": {k: str(style.get(k) or "").strip() for k in STYLE_KEYS},
            "look": {"outfit": str(look.get("outfit") or "").strip(), "background": str(look.get("background") or "").strip()},
            "change_en": str(v.get("change_en") or "").strip()}


def _model(st):
    return st.get("profile_model") or st.get("qc_model")


def specs_from_brief(st, brief, n, trace):
    """n разных паспортов по пожеланиям клиента. Возвращает (список, стоимость)."""
    res, cost, _ = chat(st, _model(st), SPEC_PROMPT.format(n=n), [{"type": "text", "text": f"Client's wishes: {brief}"}],
                        trace, "модель: описание", 1500 * n + 600, "none")
    specs = [_clean_spec(v) for v in (res.get("variants") or [])][:n]
    specs = [x for x in specs if x["appearance"]]
    if not specs:
        raise RuntimeError("ИИ не смог составить описание образа — переформулируйте пожелания")
    while len(specs) < n:          # модель вернула меньше — повторяем последний (картинки всё равно будут разными)
        specs.append(dict(specs[-1]))
    return specs, cost


def specs_for_edit(st, current, request, n, trace):
    """Паспорта после изменения внешности. current — нынешний паспорт модели."""
    text = (f"Current passport: {json.dumps(current, ensure_ascii=False)}\nClient's change request: {request}")
    # паспорт целиком переписывается в каждом варианте — лимит с запасом, иначе ответ обрезается посреди JSON
    res, cost, _ = chat(st, _model(st), EDIT_PROMPT.format(n=n), [{"type": "text", "text": text}], trace,
                        "модель: изменение", 1500 * n + 600, "none")
    specs = [_clean_spec(v) for v in (res.get("variants") or [])][:n]
    specs = [x for x in specs if x["appearance"]]
    if not specs:
        raise RuntimeError("ИИ не смог применить изменения — переформулируйте запрос")
    for x in specs:
        x["change_en"] = x["change_en"] or request
    while len(specs) < n:
        specs.append(dict(specs[-1]))
    return specs, cost


def describe(st, images, trace):
    """Паспорт по фото модели клиента. Возвращает (паспорт, стоимость)."""
    content = [{"type": "text", "text": "Photos of the person:"}]
    for data in images[:4]:
        content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(data, 1024)}})
    res, cost, _ = chat(st, _model(st), DESCRIBE_PROMPT, content, trace, "модель: описание", 1200, "none")
    spec = _clean_spec(res)
    if not spec["appearance"]:
        spec["appearance"] = str(res.get("description") or "").strip()
    return spec, cost


def _fmt(spec):
    s, look = spec.get("style") or {}, spec.get("look") or {}
    dot = lambda x, d: (x or d).strip().rstrip(".")
    return dict(appearance=dot(spec.get("appearance"), "an adult fashion model"), makeup=dot(s.get("makeup"), "natural"),
                hair=dot(s.get("hair_styling"), "natural"), acc=dot(s.get("accessories"), "none"),
                outfit=dot(look.get("outfit"), s.get("clothing_style") or "simple fitted basics"),
                vibe=dot(s.get("vibe"), "natural"), expression=dot(s.get("expression"), "relaxed natural pose, calm expression"),
                background=dot(look.get("background"), "light grey"))


def candidate_prompt(spec):
    return CANDIDATE.format(**_fmt(spec), tail=TAIL)


def edit_prompt(spec):
    return EDIT.format(change=spec.get("change_en") or "as described", **_fmt(spec), tail=TAIL)


def sheet_prompt(view):
    return SHEET.format(view=SHEET_VIEWS[view], tail=TAIL)


def style_text(style):
    """Стиль модели одной строкой для промптов кадров товара."""
    style = style or {}
    parts = [("makeup", "makeup"), ("hair_styling", "hair styling"), ("accessories", "accessories"),
             ("clothing_style", "clothing style"), ("vibe", "overall aesthetic"), ("expression", "expression and posing")]
    return "; ".join(f"{n}: {style[k].rstrip('.')}" for k, n in parts if style.get(k))


def person_hint(description, style):
    """Подсказка для профиля товара: под кого подбирать одежду, локацию и позы."""
    st = style_text(style)
    return description.strip().rstrip(".") + (f". Personal style — {st}" if st else "")


# ───────── встраивание в кадр товара ─────────

def has_person(prompt):
    """Кадр с человеком: в промпте есть блок анатомии и нет «No people»."""
    return "Anatomy: exactly one" in prompt and "No people" not in prompt


def apply(prompt, description, n_product, n_persona, style=None):
    """Встраивает модель клиента в промпт кадра. Кадры без человека не меняются."""
    if not n_persona or not has_person(prompt):
        return prompt
    who = description.strip().rstrip(".") if description else "the person from the model reference photos"
    s = style or {}
    nums = f"photo {n_product + 1}" if n_persona == 1 else f"photos {n_product + 1}-{n_product + n_persona}"
    intro = (f"Reference images: the first {n_product} attached photo(s) show the product; {nums} "
             f"show the model. The person in this photo must be EXACTLY this model: same face and facial features, "
             f"hair color, skin tone, age and body type ({who}). From the model photos take the person's appearance, "
             f"not their exact outfit, pose, background or lighting. ")
    keep = [f"makeup — {s['makeup'].rstrip('.')}" if s.get("makeup") else "",
            f"hair styling — {s['hair_styling'].rstrip('.')}" if s.get("hair_styling") else "",
            f"accessories — {s['accessories'].rstrip('.')}" if s.get("accessories") else ""]
    keep = [x for x in keep if x]
    if keep:
        intro += "Keep the model's signature styling: " + "; ".join(keep) + ". "
    if s.get("clothing_style"):
        intro += (f"Dress the model in their own clothing style ({s['clothing_style'].rstrip('.')}): if the outfit described "
                  f"below does not fit this style, replace it with an outfit in this style that keeps the product fully visible. ")
    else:
        intro += "If the outfit described below does not suit this person, dress them in a similar style that does. "
    if s.get("expression"):
        intro += (f"General posing manner: {s['expression'].rstrip('.')} (if a specific facial expression for this photo "
                  "is given below, it takes priority). ")
    # описание человека из профиля товара заменяем на модель клиента, чтобы не было двух разных людей
    out = re.sub(r"Model: .*?, tasteful high-fashion editorial style\.",
                 "Model: the same person as in the model reference photos, tasteful high-fashion editorial style.", prompt, count=1)
    if out == prompt and "Model:" in prompt:
        log.debug("модель клиента: описание человека в промпте не найдено по шаблону — добавляю только вводную")
    return intro + out
