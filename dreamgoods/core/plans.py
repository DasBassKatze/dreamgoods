"""Тарифы (подписки) и их лимиты.

Цена кадра на всех тарифах одна (наценка мастера); тарифы различаются возможностями и лимитами. Ежемесячный платёж
целиком зачисляется на баланс клиента. Условия по умолчанию — здесь; мастер может поменять их в «Финансах»
(сохраняются в настройках организации: settings["plans"] = {"seller": {"price": 1290, "projects": 5}, …}).

Лимит None — без ограничений. Тариф действует до plan_until; после — «Старт».
Клиенты без оплаты через баланс (billing=False — внутренние кабинеты мастера) работают без лимитов.
"""
import copy
from datetime import datetime, timezone

ORDER = ("start", "seller", "business", "agency")
QUALITY_NAMES = {"draft": "Черновик", "standard": "Стандарт", "premium": "Премиум", "custom": "Свой"}
YEAR_PAY_MONTHS = 11          # оплата за год: 11 месяцев, тариф — на 12

DEFAULTS = {
    "start": {"name": "Старт", "price": 0, "who": "попробовать и снимать время от времени",
              "qualities": ["draft", "standard"], "block_models": False, "manual_plan": False, "custom_market": False,
              "strictness": False, "category_apply": False, "presets": 0, "personas": 0, "styles": 1, "projects": 1,
              "users": 1, "storage_gb": 2, "parallel": 2, "support": "чат"},
    "seller": {"name": "Селлер", "price": 990, "who": "регулярные новинки одного магазина",
               "qualities": ["draft", "standard", "premium"], "block_models": False, "manual_plan": False,
               "custom_market": False, "strictness": True, "category_apply": True, "presets": 3, "personas": 1,
               "styles": 3, "projects": 3, "users": 1, "storage_gb": 10, "parallel": 4, "support": "чат"},
    "business": {"name": "Бизнес", "price": 2990, "who": "бренды и магазины с большим ассортиментом",
                 "qualities": ["draft", "standard", "premium", "custom"], "block_models": True, "manual_plan": True,
                 "custom_market": True, "strictness": True, "category_apply": True, "presets": None, "personas": 5,
                 "styles": 10, "projects": None, "users": 3, "storage_gb": 50, "parallel": 8,
                 "support": "приоритетно + помощь с пресетами"},
    "agency": {"name": "Агентство", "price": 9990, "who": "агентства и команды, которые ведут много брендов",
               "qualities": ["draft", "standard", "premium", "custom"], "block_models": True, "manual_plan": True,
               "custom_market": True, "strictness": True, "category_apply": True, "presets": None, "personas": None,
               "styles": None, "projects": None, "users": 10, "storage_gb": 200, "parallel": 16,
               "support": "персональный менеджер"},
}
POPULAR = "business"

# что можно менять мастеру: ключ → тип (None в числовых — «без ограничений»)
FIELDS = {"name": str, "price": int, "who": str, "qualities": list, "block_models": bool, "manual_plan": bool,
          "custom_market": bool, "strictness": bool, "category_apply": bool, "presets": int, "personas": int,
          "styles": int, "projects": int, "users": int, "storage_gb": int, "parallel": int, "support": str}
UNLIMITED_OK = {"presets", "personas", "styles", "projects", "users"}

# строки сравнения для сайта: (ключ, название)
FEATURES = [
    ("price", "Платёж в месяц (идёт на баланс)"),
    ("qualities", "Уровни качества"),
    ("parallel", "Генераций одновременно"),
    ("block_models", "Своя модель генерации на каждый блок кадров"),
    ("presets", "Свои пресеты"),
    ("manual_plan", "Ручной план кадров: свои промпты и модель на кадр"),
    ("category_apply", "Применение пресетов по категориям и подразделам"),
    ("custom_market", "Своя площадка: свой формат и правила обложки"),
    ("strictness", "Выбор строгости ИИ-проверки"),
    ("personas", "Свои модели-люди"),
    ("styles", "Оформление по примеру"),
    ("projects", "Проектов"),
    ("storage_gb", "Хранилище, ГБ"),
    ("users", "Пользователей в кабинете"),
    ("support", "Поддержка"),
]
# возможности, которые есть на всех тарифах (для сайта)
COMMON = ["общие пресеты студии", "площадки WB, Ozon, Яндекс Маркет, Авито: формат и обложка по правилам",
          "ИИ-проверка каждого кадра и переделка брака", "правка словами и все версии кадра",
          "удалить фон, улучшить до 4K", "импорт папки или ZIP с раскладкой по артикулам",
          "выгрузка ZIP по артикулам с отчётом", "история списаний", "баланс не сгорает"]


def _clean(key, v):
    t = FIELDS[key]
    if t is int:
        if v in (None, "") and key in UNLIMITED_OK:
            return None
        return max(0, int(v))
    if t is bool:
        return bool(v)
    if t is list:
        return [q for q in (v or []) if q in QUALITY_NAMES] or ["draft", "standard"]
    return str(v or "").strip()[:200]


def all_plans(org_settings=None):
    """Тарифы с учётом правок мастера."""
    over = (org_settings or {}).get("plans") or {}
    out = {}
    for k in ORDER:
        p = copy.deepcopy(DEFAULTS[k])
        for f, v in (over.get(k) or {}).items():
            if f in FIELDS:
                try:
                    p[f] = _clean(f, v)
                except (TypeError, ValueError):
                    pass
        p["key"] = k
        out[k] = p
    return out


def clean_overrides(data):
    """Правки мастера → только отличия от умолчаний, проверенные по типам."""
    out = {}
    for k in ORDER:
        src = (data or {}).get(k) or {}
        diff = {}
        for f in FIELDS:
            if f in src:
                v = _clean(f, src[f])
                if v != DEFAULTS[k][f]:
                    diff[f] = v
        if diff:
            out[k] = diff
    return out


def effective_key(client, now=None):
    """Действующий тариф клиента: после окончания — «Старт»."""
    if client is None:
        return None
    key = getattr(client, "plan", None) or "start"
    until = getattr(client, "plan_until", None)
    if key != "start" and until is not None:
        now = now or datetime.now(timezone.utc)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until < now:
            return "start"
    return key if key in ORDER else "start"


def limited(client):
    """Действуют ли лимиты тарифа: только для кабинетов с оплатой через баланс."""
    return client is not None and bool(client.billing)


def fmt_limit(v):
    return "без ограничений" if v is None else str(v)
