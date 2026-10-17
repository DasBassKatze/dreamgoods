"""Прайс для сайта: сколько клиент платит за кадр и операции.

Клиент платит фактическую себестоимость Polza × наценку (списание после каждой операции). Здесь — ориентир для
страницы «Цены»: средняя себестоимость готового кадра (с переделками брака и ИИ-проверкой) × наценка.
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
PROMPT = 0.05         # промпт кадра
PROFILE = 0.2         # разбор фото и профиль товара — на товар
FRAMES_PER_PRODUCT = 6
RESERVE = 0.03        # оплаченные, но потерянные задачи

# (ключ, название, модель, разрешение, попыток в среднем, ИИ-проверка)
TIERS = [
    ("draft", "Черновик", "nb21", "1K", 1.0, False, "проверить идею: без ИИ-проверки и переделок"),
    ("standard", "Стандарт", "nb21", "2K", 1.3, True, "для карточек WB, Ozon, Маркета и Авито"),
    ("standard4k", "Стандарт 4K", "nb21", "4K", 1.3, True, "крупные детали, печать, баннеры"),
    ("premium", "Премиум", "nbpro", "2K", 1.3, True, "сложные материалы, кадры с моделью"),
    ("premium4k", "Премиум 4K", "nbpro", "4K", 1.3, True, "максимум качества"),
    ("gpt", "GPT Image", "gpt", "2K", 1.3, True, "альтернативная модель для лайфстайла"),
]
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


def frame_cost(org_settings, model, res, attempts, qc):
    """Средняя себестоимость готового кадра в Polza."""
    per_try = base(org_settings, model, res) + (QC if qc else 0)
    return (per_try * attempts + PROMPT + PROFILE / FRAMES_PER_PRODUCT) * (1 + RESERVE)


def bonus_for(amount):
    rate = 0.0
    for limit, b in PACKAGES:
        if amount >= limit:
            rate = b
    return round(amount * rate, 2), rate


def price_list(org_settings, markup):
    markup = max(1.0, float(markup or 1))
    tiers = []
    for key, name, model, res, attempts, qc, note in TIERS:
        tiers.append({"key": key, "name": name, "model": MODELS[model]["name"], "resolution": res, "qc": qc, "note": note,
                      "price": _round(frame_cost(org_settings, model, res, attempts, qc) * markup)})
    ops = [{"key": key, "name": name, "note": note, "resolution": res,
            "price": _round((base(org_settings, model, res) + QC) * (1 + RESERVE) * markup)}
           for key, name, model, res, note in OPS]
    standard = next(t["price"] for t in tiers if t["key"] == "standard")
    packages = [{"amount": a, "bonus_rate": b, "bonus": round(a * b, 2), "frames": int((a * (1 + b)) // standard)}
                for a, b in PACKAGES]
    models = [{"key": k, "name": m["name"], "note": m["note"]} for k, m in MODELS.items()]
    return {"tiers": tiers, "ops": ops, "packages": packages, "models": models, "min_topup": MIN_TOPUP,
            "max_topup": MAX_TOPUP}
