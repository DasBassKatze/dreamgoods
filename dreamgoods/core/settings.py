"""Настройки: значения по умолчанию ← настройки организации ← настройки проекта.

Секреты (ключ Polza, ключ своей модели проверки) хранятся в настройках организации и в ответы API не попадают.
"""
from . import config

DEFAULTS = {
    # генерация
    "model": "google/gemini-nano-banana-2.1",
    "providers": "google-ai-studio",
    "fallback": False,
    "aspect": "3:4",
    "resolution": "2K",
    "max_refs": 6,
    "ref_side": 1536,
    "upload_refs": True,
    "series": True,             # серия товара как одна фотосессия: опорный кадр, единый свет и образ, разные эмоции        # загружать фото-референсы в хранилище Polza и передавать ссылками (надёжнее base64)
    # ИИ-проверка
    "qc_enabled": True,
    "qc_autoregen": True,
    "qc_retries": 2,
    "qc_model": "google/gemini-2.5-flash",
    "qc_base_url": "",          # пусто = Polza; иначе OpenAI-совместимый адрес (vLLM, Ollama)
    "qc_reasoning": "none",
    "qc_count": False,
    "qc_count_model": "",
    "qc_count_reasoning": "none",
    "qc_cascade": True,
    "qc_min_side": 1000,
    "qc_image_side": 2048,
    "qc_strictness": "normal",  # строгость проверки без пресета: strict | normal | critical
    "qc_checklist": "",         # чек-лист без профиля; пусто = чек-лист категории «Обувь»
    # модель (человек) на кадрах «в использовании» и общих планах
    "persona_id": 0,            # 0 — без модели клиента: внешность придумывает ИИ в профиле товара
    "persona_refs": 2,          # сколько фото модели отправлять генератору вместе с фото товара
    "preset_id": 0,             # пресет генерации проекта по умолчанию (0 — план из настроек ниже)
    "style_ref_id": 0,          # референс оформления проекта (0 — без него)
    # профиль и план кадров
    "profile_model": "",
    "plan_a": 4,
    "plan_b": 2,
    "plan_c": 1,
}

SECRETS = ("api_key", "qc_api_key")
INTS = {"max_refs": (1, 14), "ref_side": (512, 3072), "qc_retries": (0, 3), "qc_min_side": (0, 4096),
        "qc_image_side": (768, 4096), "plan_a": (0, 8), "plan_b": (0, 6), "plan_c": (0, 4),
        "persona_id": (0, 10**15), "persona_refs": (1, 4), "preset_id": (0, 10**15), "style_ref_id": (0, 10**15)}
BOOLS = ("fallback", "qc_enabled", "qc_autoregen", "qc_count", "qc_cascade", "upload_refs", "series")
REASONING = ("auto", "none", "minimal", "low", "medium", "high")


def effective(org, project):
    """Итоговые настройки для работы пайплайна (с секретами). Ключ Polza — из пула ключей клиента проекта."""
    from sqlalchemy.orm import object_session
    from . import keys
    st = dict(DEFAULTS)
    st.update({k: v for k, v in (org.settings or {}).items()})
    if project is not None:
        st.update({k: v for k, v in (project.settings or {}).items() if k not in SECRETS})
        s = object_session(project)
        if s is not None:
            secret, key_id = keys.for_client(s, project.client_id, org.id)
            if secret:
                st["api_key"], st["api_key_id"] = secret, key_id
    if not st.get("api_key"):
        st["api_key"] = config.POLZA_API_KEY
    return st


def public(org, project):
    """Настройки для интерфейса: без секретов, с признаками их наличия."""
    st = effective(org, project)
    out = {k: st.get(k) for k in DEFAULTS}
    out["has_key"] = bool(st.get("api_key"))
    out["has_qc_key"] = bool(st.get("qc_api_key"))
    return out


def clean(body):
    """Проверка и приведение типов значений из интерфейса."""
    out = {}
    for k, v in body.items():
        if k not in DEFAULTS:
            continue
        if k in INTS:
            lo, hi = INTS[k]
            v = max(lo, min(hi, int(float(v or 0))))
        elif k in BOOLS:
            v = bool(v)
        elif k == "aspect":
            from .presets import ASPECTS
            v = v if v in ASPECTS else DEFAULTS["aspect"]
        elif k == "qc_strictness":
            v = v if v in ("strict", "normal", "critical") else "normal"
        elif k in ("qc_reasoning", "qc_count_reasoning"):
            v = str(v).strip().lower()
            v = v if v in REASONING else "none"
        else:
            v = str(v or "").strip()
        out[k] = v
    return out
