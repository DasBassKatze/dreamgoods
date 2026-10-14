"""Пресеты генерации: уровень качества + план кадров по блокам.

Пресет принадлежит организации (агентству), назначается проекту по умолчанию и/или отдельным товарам.
Итоговые настройки товара: значения по умолчанию ← организация ← проект ← пресет (качество и план кадров).
"""

# Блоки кадров: ключ → (название, список кадров в профиле товара, максимум кадров)
BLOCKS = {
    "studio":    ("Товар на белом фоне, с разных сторон", "studio_shots", 8),
    "detail":    ("Детали крупно (макро)", "detail_shots", 4),
    "worn":      ("На человеке крупно / в использовании", "usage_shots", 6),
    "full":      ("На человеке в полный рост / общий план", "scene_shots", 4),
    "lifestyle": ("Лайфстайл без людей (интерьер, натюрморт)", "lifestyle_shots", 4),
}
BLOCK_ORDER = tuple(BLOCKS)

# Уровни качества. Пока это набор настроек генерации и проверки; дальше — автоподбор модели по метрикам
# (первая попытка, доля брака, цена принятого кадра) под нужный порог качества.
QUALITY = {
    "draft": {"name": "Черновик", "hint": "быстро и дёшево: 1K (900 px по короткой стороне), без перегенераций — прикинуть идеи и позы",
              "settings": {"resolution": "1K", "qc_enabled": True, "qc_autoregen": False, "qc_retries": 0, "qc_count": False}},
    "standard": {"name": "Стандарт", "hint": "для карточек: 2K (1800 px по короткой стороне), проверка ИИ и до 2 перегенераций брака",
                 "settings": {"resolution": "2K", "qc_enabled": True, "qc_autoregen": True, "qc_retries": 2, "qc_count": False}},
    "premium": {"name": "Премиум", "hint": "максимум качества: 4K (3600 px по короткой стороне), до 3 перегенераций, отдельный подсчёт ног/рук и товара",
                "settings": {"resolution": "4K", "qc_enabled": True, "qc_autoregen": True, "qc_retries": 3, "qc_count": True}},
    "custom": {"name": "Свой", "hint": "свои значения: модель, разрешение (в том числе своё в px), число перегенераций",
               "settings": {}},
}

# Разрешение пресета → короткая сторона готового кадра, px (при 3:4: 900×1200, 1800×2400, 3600×4800).
# Модель получает уровень 1K/2K/4K; если она вернула меньше (например, Nano Banana умеет только 1K — 896×1200),
# кадр увеличивается до этого размера у нас, бесплатно и без перегенерации: перегенерация разрешение не исправит.
RESOLUTION_SIDE = {"1K": 900, "2K": 1800, "4K": 3600}
OUT_SIDE_MAX = 6000
# что можно переопределить в «Своём» уровне
CUSTOM_KEYS = {"model": str, "providers": str, "resolution": str, "qc_retries": int, "qc_count": bool, "qc_model": str,
               "qc_autoregen": bool, "out_side": int}

# Профили площадок: формат кадра, минимальная сторона (для техпроверки) и правила главного фото (обложки).
# Источник: требования площадок по состоянию на сентябрь 2026 (selsup.ru). Площадки их меняют — значения
# в пресете можно поправить вручную (площадка «Своя»).
MARKETS = {
    "none": {"name": "Без площадки", "aspect": "", "min_side": 0, "hint": "формат и обложка — как в настройках проекта",
             "cover_bg": "", "cover_fill": "", "cover_extra": ""},
    "wb": {"name": "Wildberries", "aspect": "3:4", "min_side": 900,
           "hint": "3:4, от 700×900 px; главное фото — товар целиком на чистом ровном нейтральном фоне, контрастном товару; "
                   "без логотипов, бирок, акций, водяных знаков и слов вроде «хит» и «распродажа»",
           "cover_bg": "a clean, even, neutral light background that contrasts with the product",
           "cover_fill": "about 80% of the frame",
           "cover_extra": "the whole product is visible and in sharp focus, without packaging, no logos, tags, badges or promo text"},
    "ozon": {"name": "Ozon", "aspect": "3:4", "min_side": 900,
             "hint": "3:4, рекомендуют 900×1200 px; главное фото — настоящий цветной снимок, без домашней обстановки с "
                     "посторонними предметами и тенями; одежду можно показывать на человеке",
             "cover_bg": "a clean plain light studio background, no home setting, no extraneous objects",
             "cover_fill": "about 80% of the frame",
             "cover_extra": "a realistic color photo of the product, no harsh cast shadows, no text, no price or discount badges"},
    "ymarket": {"name": "Яндекс Маркет", "aspect": "3:4", "min_side": 900,
                "hint": "приводится к 3:4, от 300×300 px; главное фото — лучше на белом фоне, товар не меньше 2/3 кадра, "
                        "без посторонних людей и животных, без водяных знаков и логотипа магазина",
                "cover_bg": "a pure white background (#FFFFFF)",
                "cover_fill": "at least two thirds of the frame",
                "cover_extra": "no extraneous people or animals, no watermarks, no store logos"},
    "custom": {"name": "Своя", "aspect": "3:4", "min_side": 1000, "hint": "свои формат и правила обложки",
               "cover_bg": "a pure white background (#FFFFFF)", "cover_fill": "about 80% of the frame", "cover_extra": ""},
}
ASPECTS = ("3:4", "4:5", "9:16", "1:1", "2:3", "16:9")

# Строгость ИИ-проверки: что считать браком
STRICTNESS = {
    "strict": {"name": "Строго", "hint": "брак — любое заметное отличие от товара: оттенок, фактура, строчки, мелкий декор"},
    "normal": {"name": "Обычно", "hint": "брак — то, что делает фото непригодным для карточки; мелочи не считаются"},
    "critical": {"name": "Только критичное", "hint": "брак — другой товар, лишние/недостающие части или ноги-руки, "
                                                    "неверное количество, испорченный текст; остальное пропускается"},
}


def clean_market(m):
    m = m or {}
    key = m.get("key") if m.get("key") in MARKETS else "none"
    out = {"key": key, "cover": bool(m.get("cover", key != "none"))}
    if key == "custom":
        base = MARKETS["custom"]
        out["aspect"] = m.get("aspect") if m.get("aspect") in ASPECTS else base["aspect"]
        out["min_side"] = max(0, min(4096, int(m.get("min_side") or base["min_side"])))
        for k in ("cover_bg", "cover_fill", "cover_extra"):
            out[k] = str(m.get(k) if m.get(k) is not None else base[k]).strip()[:400]
    return out


def market_rules(m):
    """Итоговые правила площадки (для custom — из пресета, иначе — из справочника)."""
    m = clean_market(m)
    base = dict(MARKETS[m["key"]])
    if m["key"] == "custom":
        base.update({k: m[k] for k in ("aspect", "min_side", "cover_bg", "cover_fill", "cover_extra")})
    base["key"], base["cover"] = m["key"], m["cover"] and m["key"] != "none"
    return base


DEFAULT_PRESETS = [
    {"name": "Обувь — стандарт", "description": "4 ракурса на белом, деталь, 2 на ноге, 1 в полный рост",
     "quality": "standard", "plan": {"studio": 4, "detail": 1, "worn": 2, "full": 1, "lifestyle": 0},
     "market": {"key": "wb", "cover": True}},
    {"name": "Одежда — на модели", "description": "2 на белом, деталь ткани, 3 на модели крупно, 2 в полный рост",
     "quality": "standard", "plan": {"studio": 2, "detail": 1, "worn": 3, "full": 2, "lifestyle": 0},
     "market": {"key": "wb", "cover": True}},
    {"name": "Товар для дома — лайфстайл", "description": "3 на белом, 2 детали, 3 в интерьере",
     "quality": "standard", "plan": {"studio": 3, "detail": 2, "worn": 0, "full": 0, "lifestyle": 3}},
    {"name": "Черновик — проверить идею", "description": "по 1 кадру каждого вида дёшево",
     "quality": "draft", "plan": {"studio": 1, "detail": 0, "worn": 1, "full": 1, "lifestyle": 0}},
]


MANUAL_MAX_ITEMS, MANUAL_MAX_COUNT, MANUAL_MAX_TOTAL = 12, 8, 30
# блок кадра из prompts.block_of → ключ блока пресета
BLOCK_OF_PROMPT = {"studio": "studio", "detail": "detail", "usage": "worn", "scene": "full", "lifestyle": "lifestyle"}


def clean_manual(items):
    """Ручной план: [{title, prompt, block, count, model}] — свои методы съёмки."""
    out, total = [], 0
    for it in (items or [])[:MANUAL_MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        prompt = str(it.get("prompt") or "").strip()[:2000]
        if not prompt:
            continue
        n = max(1, min(MANUAL_MAX_COUNT, int(it.get("count") or 1)))
        n = min(n, MANUAL_MAX_TOTAL - total)
        if n <= 0:
            break
        total += n
        out.append({"title": (str(it.get("title") or "").strip() or "Кадр")[:60], "prompt": prompt,
                    "block": it.get("block") if it.get("block") in BLOCKS else "studio", "count": n,
                    "model": str(it.get("model") or "").strip()[:120]})
    return out


def clean_block_models(d):
    """Модель генерации для каждого блока: {studio: "google/…", …}; пусто — модель пресета/проекта."""
    return {k: str((d or {}).get(k) or "").strip()[:120] for k in BLOCK_ORDER if str((d or {}).get(k) or "").strip()}


def manual_plan(items):
    plan = {k: 0 for k in BLOCK_ORDER}
    for it in items:
        plan[it["block"]] += it["count"]
    return plan


def clean_plan(plan):
    plan = plan or {}
    return {k: max(0, min(BLOCKS[k][2], int(plan.get(k) or 0))) for k in BLOCK_ORDER}


def clean_custom(values):
    out = {}
    for k, t in CUSTOM_KEYS.items():
        v = (values or {}).get(k)
        if v in (None, ""):
            continue
        if k == "out_side":
            out[k] = max(0, min(OUT_SIDE_MAX, int(float(v))))
            continue
        out[k] = max(0, min(3, int(v))) if t is int else bool(v) if t is bool else str(v).strip()
    if out.get("resolution") not in (None, "1K", "2K", "4K"):
        out.pop("resolution")
    if not out.get("out_side"):
        out.pop("out_side", None)
    elif not out.get("resolution"):     # своё разрешение в px — модели заказываем ближайший уровень не меньше него
        out["resolution"] = next((r for r, side in RESOLUTION_SIDE.items() if side >= out["out_side"]), "4K")
    return out


def out_side(st):
    """Короткая сторона готового кадра, px: своё значение пресета → уровень разрешения; не меньше минимума площадки."""
    side = int(st.get("out_side") or 0) or RESOLUTION_SIDE.get(str(st.get("resolution") or ""), 0)
    return max(side, int(st.get("qc_min_side") or 0))


def plan_from_settings(st):
    """План без пресета — из старых настроек проекта (белый фон / в использовании / общий план)."""
    return {"studio": int(st.get("plan_a") or 0), "detail": 0, "worn": int(st.get("plan_b") or 0),
            "full": int(st.get("plan_c") or 0), "lifestyle": 0}


def plan_of(st):
    return clean_plan(st.get("plan") or plan_from_settings(st))


def apply(st, preset):
    """Действующие настройки товара с пресетом (preset — строка таблицы или None)."""
    if preset is None:
        return st
    q = QUALITY.get(preset.quality) or QUALITY["standard"]
    out = dict(st)
    out.update(q["settings"])
    out.pop("out_side", None)           # своё разрешение из настроек проекта не переносим в уровень пресета
    if preset.quality == "custom":
        out.update(clean_custom(preset.custom))
    out["plan_mode"] = "manual" if preset.plan_mode == "manual" else "auto"
    out["manual"] = clean_manual(preset.manual) if out["plan_mode"] == "manual" else []
    out["plan"] = manual_plan(out["manual"]) if out["plan_mode"] == "manual" else clean_plan(preset.plan)
    out["block_models"] = clean_block_models(preset.block_models)
    out["preset_id"], out["preset_name"] = preset.id, preset.name
    out["qc_strictness"] = preset.strictness if preset.strictness in STRICTNESS else "normal"
    rules = market_rules(preset.market)
    out["market"] = rules
    if rules["aspect"]:
        out["aspect"] = rules["aspect"]
    if rules["min_side"]:
        out["qc_min_side"] = rules["min_side"]
    return out


def total(plan):
    return sum(clean_plan(plan).values())


def preset_total(preset):
    if preset.plan_mode == "manual":
        return sum(it["count"] for it in clean_manual(preset.manual))
    return total(preset.plan)


def model_for(st, block_key, frame_model=""):
    """Модель генерации кадра: своя у ручного метода → модель блока → модель пресета/проекта.
    Если модель сменилась, провайдера выбирает Polza (заданный провайдер может не поддерживать другую модель)."""
    m = (frame_model or (st.get("block_models") or {}).get(block_key) or "").strip()
    if not m or m == st.get("model"):
        return st
    return dict(st, model=m, providers="")
