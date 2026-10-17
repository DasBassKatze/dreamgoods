"""Прайс для сайта: сколько клиент платит за кадр и операции.

Клиент платит фактическую себестоимость Polza × наценку (списание после каждой операции). Здесь — ориентир для
страницы «Цены»: средняя себестоимость готового кадра (с переделками брака и ИИ-проверкой) × наценка.
Уровни качества, площадки и пресеты берутся из студии (core/presets и общие пресеты организации), поэтому сайт
всегда показывает то же, что пользователь выберет при генерации.
Базовые цены Polza можно переопределить в настройках организации: settings["price_base"] = {"nb21": {"2K": 4.5}, …}.
"""
import math

# Цены Polza за одно изображение, ₽ (страницы моделей Polza: Nano Banana 2.1 — от 3 до 6,75; Pro — от 13,5 до 18;
# GPT Image — от 4). Разбивка по разрешениям — оценка, уточняется по журналу расходов.
MODELS = {
    "nb21": {"name": "Nano Banana 2.1", "note": "быстрая и недорогая, основная модель", "prices": {"1K": 3.0, "2K": 4.5, "4K": 6.75}},
    "nbpro": {"name": "Nano Banana Pro", "note": "максимальная детализация, сложные материалы и люди",
              "prices": {"1K": 13.5, "2K": 13.5, "4K": 18.0}},
    "gpt": {"name": "GPT Image", "note": "другая манера: мягкий свет, лайфстайл", "prices": {"1K": 4.0, "2K": 6.0, "4K": 9.0}},
}
QC = 0.055            # ИИ-проверка одной попытки (Gemini 2.5 Flash Lite)
QC_PRO = 0.8          # ИИ-проверка на Gemini 2.5 Pro (уровень «Премиум»): дороже, с «размышлениями»
PROMPT = 0.05         # промпт кадра
PROFILE = 0.2         # разбор фото и профиль товара — на товар
FRAMES_PER_PRODUCT = 6
RESERVE = 0.03        # оплаченные, но потерянные задачи

# Уровни качества — те же, что в пресетах студии (core/presets.QUALITY): разрешение, ИИ-проверка, перегенерации.
# Доля брака на попытку — для оценки среднего числа попыток: 1 + p + p² + … (до числа перегенераций).
REJECT_RATE = 0.25
TIER_NOTES = {
    "draft": "прикинуть идеи и позы",
    "standard": "для карточек WB, Ozon, Маркета и Авито",
    "premium": "сложные материалы и кадры с моделью; брак ищет Gemini 2.5 Pro, отдельно проверяет руки, ноги и товар",
    "custom": "своя модель, разрешение и число перегенераций — цена по выбранной модели",
}
MARKET_KEYS = ("wb", "ozon", "ymarket", "avito")


def model_key(model_id):
    """Идентификатор модели Polza → ключ прайса."""
    m = (model_id or "").lower()
    if "gpt" in m or "openai" in m:
        return "gpt"
    if "pro" in m:
        return "nbpro"
    return "nb21"


def quality_cost(org_settings, st):
    """Средняя себестоимость готового кадра по действующим настройкам генерации (уровень качества пресета)."""
    model = model_key(st.get("model"))
    res = st.get("resolution") if st.get("resolution") in MODELS[model]["prices"] else "2K"
    qc = bool(st.get("qc_enabled", True))
    retries = int(st.get("qc_retries") or 0) if qc and st.get("qc_autoregen", True) else 0
    attempts = sum(REJECT_RATE ** k for k in range(retries + 1))
    checks = (1 + (1 if st.get("qc_count") else 0)) if qc else 0
    qc_one = QC_PRO if "pro" in (st.get("qc_model") or "").lower() else QC
    per_try = base(org_settings, model, res) + qc_one * checks
    return (per_try * attempts + PROMPT + PROFILE / FRAMES_PER_PRODUCT) * (1 + RESERVE), model, res, retries, qc


# операции над готовым кадром: (ключ, название, модель, разрешение, описание)
OPS = [
    ("edit", "Правка кадра по тексту", "nb21", "2K", "«сделай фон светлее», «убери складку»"),
    ("remove_bg", "Удалить фон", "nb21", "2K", "чистый белый фон под требования площадки"),
    ("upscale", "Улучшить до 4K", "nb21", "4K", "та же картинка в 4K, детальнее и чище"),
    ("persona", "Вариант образа модели", "nb21", "2K", "генерация своей модели для съёмок"),
]
# пакеты пополнения: (сумма, бонус)
PACKAGES = [(500, 0.0), (1500, 0.05), (5000, 0.10), (15000, 0.15)]
MIN_TOPUP, MAX_TOPUP = 300, 1_000_000


def _round(v):
    """Цена для витрины — с шагом 0,5 ₽ вверх."""
    return math.ceil(v * 2 - 1e-9) / 2


def base(org_settings, model, res):
    over = ((org_settings or {}).get("price_base") or {}).get(model) or {}
    return float(over.get(res) or MODELS[model]["prices"][res])


def bonus_for(amount):
    rate = 0.0
    for limit, b in PACKAGES:
        if amount >= limit:
            rate = b
    return round(amount * rate, 2), rate


def price_list(org_settings, markup, presets=None):
    """Прайс для сайта. Уровни качества, площадки и пресеты — те же, что в студии."""
    from . import presets as P
    from .settings import DEFAULTS
    markup = max(1.0, float(markup or 1))
    st0 = {**DEFAULTS, **(org_settings or {})}
    tiers = []
    for key in ("draft", "standard", "premium"):
        q = P.QUALITY[key]
        cost, model, res, retries, qc = quality_cost(org_settings, {**st0, **q["settings"]})
        tiers.append({"key": key, "name": q["name"], "model": MODELS[model]["name"], "resolution": res,
                      "side": P.RESOLUTION_SIDE.get(res, 0), "qc": qc, "retries": retries, "note": TIER_NOTES[key],
                      "price": _round(cost * markup)})
    for t in tiers:
        t["from"] = False
    tiers.append({"key": "custom", "name": P.QUALITY["custom"]["name"], "model": "модель на выбор", "resolution": "1K–4K",
                  "side": 0, "qc": True, "retries": 0, "note": TIER_NOTES["custom"], "price": tiers[0]["price"], "from": True})
    ops = [{"key": key, "name": name, "note": note, "resolution": res,
            "price": _round((base(org_settings, model, res) + QC) * (1 + RESERVE) * markup)}
           for key, name, model, res, note in OPS]
    by_key = {t["key"]: t["price"] for t in tiers}
    standard = by_key["standard"]
    packages = [{"amount": a, "bonus_rate": b, "bonus": round(a * b, 2), "frames": int((a * (1 + b)) // standard)}
                for a, b in PACKAGES]
    models = [{"key": k, "name": m["name"], "note": m["note"]} for k, m in MODELS.items()]
    markets = [{"key": k, "name": P.MARKETS[k]["name"], "aspect": P.MARKETS[k]["aspect"], "min_side": P.MARKETS[k]["min_side"],
                "hint": P.MARKETS[k]["hint"]} for k in MARKET_KEYS]
    out_presets = []
    for p in (presets if presets is not None else P.DEFAULT_PRESETS):
        quality = p.get("quality") if p.get("quality") in P.QUALITY else "standard"
        if quality == "custom":
            cost, *_ = quality_cost(org_settings, {**st0, **P.clean_custom(p.get("custom"))})
            price = _round(cost * markup)
        else:
            main = P.clean_main_model(p.get("custom"))
            cost, *_ = quality_cost(org_settings, {**st0, **P.QUALITY[quality]["settings"], **main})
            price = _round(cost * markup)
        frames = p["total"] if "total" in p else P.total(p.get("plan"))
        if not frames:
            continue
        mk = P.clean_market(p.get("market"))["key"]
        out_presets.append({"name": p["name"], "description": p.get("description") or "", "quality": quality,
                            "quality_name": P.QUALITY[quality]["name"], "frames": frames, "frame_price": price,
                            "market": P.MARKETS[mk]["name"] if mk != "none" else "", "price": round(price * frames, 2)})
    return {"tiers": tiers, "ops": ops, "packages": packages, "models": models, "markets": markets, "presets": out_presets,
            "min_topup": MIN_TOPUP, "max_topup": MAX_TOPUP}
