"""Клиент Polza.ai: генерация изображений (асинхронно, без повтора после таймаута — защита от двойной оплаты),
баланс, каталог моделей и OpenAI-совместимый чат для проверки/профилей (подходит и для своего vLLM/Ollama)."""
import base64
import hashlib
import json
import re
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.logs import log, mb
from . import throttle
from .model_notes import note_for

API = "https://polza.ai/api/v1"
# Баланс по документации Polza: GET /api/v1/balance → {"amount": "9.28"} — то же число, что в личном кабинете.
# v2 — запасной вариант (там может быть «available» — доступно с учётом резервов под незавершённые задачи).
BALANCE_URLS = ("https://polza.ai/api/v1/balance", "https://polza.ai/api/v2/balance")
POLL_EVERY = 4
POLL_TIMEOUT = 15 * 60           # столько ждём результат в задании; дальше задача «дозагружается» в фоне
POLL_GIVE_UP = 24 * 3600         # результат Polza хранит сутки — дольше ждать бессмысленно


# ───────── транспорт: одно пуловое соединение на весь процесс ─────────
# Раньше каждый запрос открывал новое TLS-соединение; при 4–8 параллельных генерациях с длинным опросом это давало
# обрывы («Connection reset», «RemoteDisconnected»). Теперь: общий пул keep-alive соединений и автоповторы
# там, где повтор безопасен:
#   • ошибка установки соединения (запрос ещё не ушёл) — повтор для любых запросов, в том числе платных POST;
#   • обрыв/таймаут чтения и 429/5xx — повтор только для GET (опрос статуса, скачивание, баланс): они бесплатны.
POOL_SIZE = 128


def _make_session():
    retry = Retry(total=6, connect=5, read=3, status=4, backoff_factor=1.5, raise_on_status=False,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET", "HEAD"}),
                  respect_retry_after_header=True)
    sess = requests.Session()
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=POOL_SIZE, max_retries=retry, pool_block=False)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({"User-Agent": "DreamGoods/1.0", "Connection": "keep-alive"})
    return sess


http = _make_session()


def _not_sent(e):
    """True, если запрос точно не дошёл до сервера (повтор безопасен даже для платного POST)."""
    if isinstance(e, requests.ConnectTimeout):
        return True
    txt = f"{type(e).__name__} {e}"
    return any(x in txt for x in ("NewConnectionError", "NameResolutionError", "Failed to resolve", "ConnectTimeoutError",
                                  "getaddrinfo")) and "RemoteDisconnected" not in txt \
        and "Connection aborted" not in txt and "reset by peer" not in txt


class AspectUnsupported(RuntimeError):
    """Модель не умеет нужный формат кадра (например, 3:4) — Polza вернула список допустимых."""
    def __init__(self, msg, allowed):
        super().__init__(msg)
        self.allowed = allowed


_aspects = {}          # модель → форматы, которые она умеет (узнаём из ответа Polza)


def _ratio(a):
    w, h = (int(x) for x in a.split(":"))
    return w / h


def nearest_aspect(target, allowed):
    """Ближайший допустимый формат; при равенстве — тот, что выше (обрезать по высоте безопаснее для товара)."""
    t = _ratio(target)
    return min(allowed, key=lambda a: (abs(_ratio(a) - t), _ratio(a)))


def crop_to_aspect(img_bytes, target):
    """Обрезка по центру до нужного формата (после генерации в ближайшем допустимом)."""
    from .images import DECODE_SLOTS
    with DECODE_SLOTS:
        return _crop_to_aspect(img_bytes, target)


def _crop_to_aspect(img_bytes, target):
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(img_bytes))
    w, h = im.size
    t = _ratio(target)
    if abs(w / h - t) < 0.01:
        return img_bytes
    if w / h > t:                       # шире нужного — режем бока
        nw = round(h * t)
        box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
    else:                               # выше нужного — режем верх и низ
        nh = round(w / t)
        box = (0, (h - nh) // 2, w, (h - nh) // 2 + nh)
    out = BytesIO()
    im.crop(box).save(out, "PNG")
    return out.getvalue()


def _with_aspect(st, prompt, target, tag):
    """Если модель не умеет формат кадра — генерируем в ближайшем и потом обрезаем до нужного."""
    allowed = _aspects.get(st["model"])
    if not allowed or target in allowed:
        return st, prompt, None
    use = nearest_aspect(target, allowed)
    log.info("%s модель %s не умеет формат %s — генерирую %s и обрежу до %s", tag, st["model"], target, use, target)
    note = (f"\n\nFRAMING: this image will be center-cropped from {use} to {target}. Keep the product and every important "
            "detail well inside the central area with generous empty margins on the edges that will be cut.")
    return dict(st, aspect=use), prompt + note, target


class Pending(RuntimeError):
    """Задача Polza принята (и, возможно, оплачена), но результат пока не получен: связь оборвалась, вышло время
    ожидания или не скачалась картинка. Результат дозагружается в фоне (workers/resume.py) — без повторной оплаты."""
    def __init__(self, msg, task_id):
        super().__init__(msg)
        self.task_id = task_id
KIND = {"сверка": "qc", "подсчёт": "count", "ожидания": "spec", "профиль": "profile", "сортировка": "sort",
        "ракурсы": "views", "модель: описание": "persona", "модель: изменение": "persona", "подразделы": "profile", "оформление": "style"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class TaskFailed(RuntimeError):
    """Задача Polza завершилась со статусом failed/cancelled (data — полный ответ)."""
    def __init__(self, msg, data):
        super().__init__(msg)
        self.data = data


# ───────── загрузка референсов в хранилище Polza (Storage API) ─────────
# Base64 в запросе Polza сама перекладывает в хранилище, и провайдер (Google) иногда не может скачать файл:
# «Image fetch failed. Check access settings or use our File Upload API instead». Поэтому загружаем фото сами
# (TEMP_UPLOAD живёт 24 ч) и передаём ссылки. Одно и то же фото в пределах суток загружается один раз.
STORAGE_URL = f"{API}/storage/upload"
_uploads, _uploads_lock = {}, threading.Lock()


def _upload_one(key, item, tag, force=False):
    raw = item.get("data") or ""
    b64 = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    mime = raw[5:raw.index(";")] if raw.startswith("data:") and ";" in raw else "image/jpeg"
    h = hashlib.sha1(b64.encode()).hexdigest()
    now = time.time()
    with _uploads_lock:
        hit = _uploads.get((key[-8:], h))
    if hit and hit[1] > now and not force:
        return {"type": "url", "data": hit[0]}, True
    lim = throttle.limiter("upload", key)
    with throttle.upload_slots:
        lim.acquire()
        r = http.post(STORAGE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=(20, 120),
                      json={"base64": b64, "mimeType": mime, "storagePolicy": "TEMP_UPLOAD"})
    if r.status_code in (429, 503):
        lim.on_throttle(r.headers.get("Retry-After"))
    else:
        lim.on_ok()
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    url = (r.json() or {}).get("url")
    if not url:
        raise RuntimeError("хранилище не вернуло ссылку")
    with _uploads_lock:
        _uploads[(key[-8:], h)] = (url, now + 20 * 3600)
    return {"type": "url", "data": url}, False


def upload_refs(key, refs, tag="", force=False):
    """base64-референсы → ссылки в хранилище Polza. Если загрузка не удалась — оставляем base64 (как раньше)."""
    out, up, cached = [], 0, 0
    for item in refs:
        if item.get("type") != "base64":
            out.append(item)
            continue
        try:
            new, was_cached = _upload_one(key, item, tag, force)
            out.append(new)
            cached += was_cached
            up += not was_cached
        except Exception as e:
            log.warning("%s фото-референс не загружен в хранилище Polza (%s) — отправляю внутри запроса", tag, e)
            out.append(item)
    if up or cached:
        log.info("%s референсы в хранилище Polza: загружено %d, уже были %d", tag, up, cached)
    return out


RETRY_CODES = ("INTERNAL_ERROR",)        # сбой у провайдера; ошибки модерации, лимитов и т. п. не повторяем


def generate(st, key, prompt, refs, tag="", on_task=None):
    """Генерация с защитой от сбоев провайдера: референсы — ссылками из хранилища Polza; если задача упала
    из-за внутренней ошибки (например, провайдер не скачал фото) и не была оплачена — один повтор через 15 с."""
    use_storage = st.get("upload_refs", True)
    payload = upload_refs(key, refs, tag) if use_storage else refs
    target = st["aspect"]
    st, prompt, crop = _with_aspect(st, prompt, target, tag)
    try:
        try:
            data = _generate_once(st, key, prompt, payload, tag, on_task)
        except AspectUnsupported as e:
            _aspects[st["model"]] = e.allowed
            st, prompt, crop = _with_aspect(dict(st, aspect=target), prompt, target, tag)
            data = _generate_once(st, key, prompt, payload, tag, on_task)
        if crop:
            data["_crop_to"] = crop
        return data
    except TaskFailed as e:
        er = e.data.get("error") if isinstance(e.data.get("error"), dict) else {}
        code = str(er.get("code") or "").upper()
        raw_err = str((er.get("metadata") or {}).get("raw") or "").lower()
        usage = e.data.get("usage") or {}
        paid = _num(usage.get("cost_rub")) or _num(usage.get("cost")) or 0
        if paid or not (code in RETRY_CODES or "image fetch failed" in raw_err):
            raise
        log.warning("%s сбой на стороне провайдера (%s) — задача не оплачена, повторяю через 15 с, фото загружаю заново",
                    tag, raw_err[:160] or code)
        time.sleep(15)
        payload = upload_refs(key, refs, tag, force=True)
        data = _generate_once(st, key, prompt, payload, tag, on_task)
        if crop:
            data["_crop_to"] = crop
        return data


def _generate_once(st, key, prompt, refs, tag="", on_task=None):
    from ..services import payments
    with payments.call("generation", st["model"]) as oid:
        data = _generate_paid(st, key, prompt, refs, tag, on_task)
        payments.settle(oid, cost_of(data), provider=data.get("provider", ""))
        data["_paid_operation"] = oid
        return data


def _generate_paid(st, key, prompt, refs, tag="", on_task=None):
    """refs: [{"type": "base64", "data": "data:image/jpeg;base64,…"}]. Возвращает ответ Polza со статусом completed."""
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "model": st["model"],
        "input": {
            "prompt": prompt,
            "aspect_ratio": st["aspect"],
            "image_resolution": st["resolution"],
            "output_format": "png",
        },
        "async": True,
    }
    if refs:                       # без референсов (образ модели с нуля) поле не передаём
        body["input"]["images"] = refs
    providers = [p.strip() for p in str(st.get("providers") or "").split(",") if p.strip()]
    if providers:
        body["provider"] = {"order": providers, "allow_fallbacks": bool(st.get("fallback"))}
    size = sum(len(x.get("data", "")) for x in refs) + len(prompt)
    log.info("%s → Polza: %s · провайдер %s · %s %s · референсов %d · запрос %s", tag, st["model"],
             ",".join(providers) or "авто", st["resolution"], st["aspect"], len(refs), mb(size))
    log.debug("%s промпт (%d симв.): %s", tag, len(prompt), prompt)
    t0 = time.time()
    data = _submit(headers, body, tag)
    task_id = data.get("id") or data.get("taskId") or data.get("task_id")
    log.info("%s задача Polza %s принята за %.1f с, статус %s", tag, task_id or "—", time.time() - t0, data.get("status"))
    log.debug("%s ответ на создание: %s", tag, _short(data))
    from ..services import payments
    payments.submitted(str(task_id or ""))
    if task_id and on_task:
        on_task(str(task_id))     # номер задачи — сразу в базу: даже при обрыве результат можно будет забрать
    if data.get("status") not in ("completed", "failed", "cancelled"):
        if not task_id:
            raise RuntimeError("Polza не вернула номер задачи")
        data = wait_task(key, task_id, tag, t0, POLL_TIMEOUT)
    return finish(data, tag, t0)


def _submit(headers, body, tag):
    """POST /media. Скорость — адаптивный ограничитель ключа (throttle.py). Повтор только если запрос точно не ушёл
    или Polza ответила «занято» (задача не создана) — иначе риск двойной оплаты."""
    key = headers.get("Authorization", "")[7:]
    lim = throttle.limiter("submit", key)
    busy = 0
    for attempt in range(12):
        lim.acquire()
        try:
            from ..services import payments
            payments.submitted()
            r = http.post(f"{API}/media", headers=headers, json=body, timeout=(20, 180))
        except requests.RequestException as e:
            if _not_sent(e) and attempt < 3:
                log.warning("%s нет соединения с Polza (попытка %d), запрос не ушёл — повторяю: %s", tag, attempt + 1, e)
                time.sleep(5 * (attempt + 1))
                continue
            if _not_sent(e):
                payments.not_charged()
                raise RuntimeError(f"нет соединения с Polza: {e}")
            log.error("%s связь с Polza оборвалась после отправки запроса — повтор не делаю (риск двойной оплаты): %s", tag, e)
            raise RuntimeError("связь с Polza оборвалась сразу после отправки запроса; повтор не делался, чтобы не "
                               "заплатить дважды. Если в кабинете Polza генерация списана — перегенерируйте кадр позже")
        if r.status_code == 429 and busy < 8:
            busy += 1
            lim.on_throttle(r.headers.get("Retry-After"))     # все потоки этого ключа притормозят
            log.debug("%s Polza занята: HTTP %s (%d-й раз): %s", tag, r.status_code, busy, r.text[:200])
            continue
        if r.status_code >= 400:
            if r.status_code < 500:
                payments.not_charged()
            try:
                msg = r.json().get("error", {}).get("message") or r.text
            except Exception:
                msg = r.text
            if r.status_code == 400 and "aspect_ratio" in msg:
                allowed = re.findall(r"\b\d{1,2}:\d{1,2}\b", msg.split("Допустимые", 1)[-1] if "Допустимые" in msg
                                     else msg.split("allowed", 1)[-1])
                if allowed:     # отказ до создания задачи — ничего не оплачено, можно повторить в другом формате
                    raise AspectUnsupported(msg, allowed)
            log.error("%s Polza HTTP %s: %s", tag, r.status_code, msg[:500])
            raise RuntimeError(f"HTTP {r.status_code}: {msg[:300]}")
        lim.on_ok()
        return r.json()
    raise RuntimeError("Polza перегружена — задача не создана, попробуйте позже")


def get_task(key, task_id, timeout=(10, 45)):
    """Один опрос статуса задачи (GET — безопасно повторять; пул сам повторит обрыв/5xx)."""
    r = http.get(f"{API}/media/{task_id}", headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


_poller = None


def poller():
    global _poller
    if _poller is None:
        _poller = throttle.TaskPoller(lambda k, t: get_task(k, t))
    return _poller


def wait_task(key, task_id, tag, t0, limit):
    """Ждём завершения задачи через общий опросчик (throttle.TaskPoller): поток задания спит, статусы опрашиваются
    пакетно. Временные сбои связи не прерывают ожидание. Нет результата за limit секунд — Pending
    (задача не потеряна и дозагрузится в фоне)."""
    data = poller().wait(key, task_id, tag, t0, limit)
    if data is None:
        raise Pending(f"Polza генерирует дольше {int(limit) // 60} мин; задача {task_id} не потеряна — "
                      "результат будет дозагружен автоматически", task_id)
    return data


def finish(data, tag, t0):
    usage = data.get("usage") or {}
    if data.get("status") != "completed":
        err = data.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        log.error("%s генерация %s: %s", tag, data.get("status"), _short(data))
        raw = (err.get("metadata") or {}).get("raw") if isinstance(err, dict) else ""
        raise TaskFailed(f"{data.get('status')}: {msg}" + (f" ({raw})" if raw else ""), data)
    log.info("%s ✓ сгенерировано за %.0f с · %s · стоимость %s ₽", tag, time.time() - t0,
             data.get("provider") or "—", usage.get("cost_rub") or usage.get("cost") or "?")
    log.debug("%s итоговый ответ: %s", tag, _short(data))
    return data


def cost_of(data):
    usage = data.get("usage") or {}
    return _num(usage.get("cost_rub")) or _num(usage.get("cost")) or 0.0


def _short(obj, limit=1500):
    """JSON для лога без мегабайтов base64."""
    def cut(v):
        if isinstance(v, dict):
            return {k: cut(x) for k, x in v.items()}
        if isinstance(v, list):
            return [cut(x) for x in v]
        if isinstance(v, str) and len(v) > 300:
            return v[:80] + f"…<{len(v)} симв.>"
        return v
    try:
        return json.dumps(cut(obj), ensure_ascii=False)[:limit]
    except Exception:
        return str(obj)[:limit]


def extract_image(data):
    img = _extract_raw(data)
    if img and data.get("_crop_to"):
        img = crop_to_aspect(img, data["_crop_to"])
    return img


def _extract_raw(data):
    items = data.get("data")
    items = [items] if isinstance(items, dict) else list(items or [])
    if isinstance(data.get("output"), dict):
        items.append(data["output"])
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("b64_json"):
            b = it["b64_json"]
            return base64.b64decode(b.split(",", 1)[1] if "," in b else b)
        if it.get("url"):
            return download(it["url"])
    return None


def download(url, tries=4):
    """Скачивание готовой картинки: несколько попыток (результат уже оплачен — терять его нельзя)."""
    last = None
    for a in range(tries):
        try:
            log.debug("скачиваю результат (попытка %d): %s", a + 1, url)
            with throttle.download_slots:
                r = http.get(url, timeout=(15, 180))
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("пустой файл")
            return r.content
        except Exception as e:
            last = e
            log.warning("не удалось скачать результат (попытка %d/%d): %s", a + 1, tries, str(e)[:200])
            time.sleep(5 * (a + 1))
    raise RuntimeError(f"не удалось скачать готовую картинку: {last}")

_balances, _bal_lock = {}, threading.Lock()     # ключ → {t, value, error, busy}


def _bal(key):
    with _bal_lock:
        return _balances.setdefault(key or "", {"t": 0, "value": None, "error": "", "busy": False})


def balance(key, force=False):
    """Баланс ключа Polza. force=False: отдаёт кэш и при необходимости обновляет его в фоне, не задерживая интерфейс."""
    b = _bal(key)
    if not force:
        if time.time() - b["t"] >= 30 and not b["busy"]:
            b["busy"] = True
            threading.Thread(target=lambda: balance(key, True), daemon=True, name="balance").start()
        return b
    try:
        return _balance_fetch(key)
    finally:
        b["busy"] = False


def _balance_fetch(k):
    b = _bal(k)
    if not k:
        b.update(t=time.time(), value=None, error="нет API-ключа")
        return b
    try:
        j, last = None, None
        for url in BALANCE_URLS:
            try:
                r = http.get(url, headers={"Authorization": f"Bearer {k}"}, timeout=15)
                r.raise_for_status()
                j = r.json()
                break
            except Exception as e:
                last = e
                if getattr(getattr(e, "response", None), "status_code", None) in (401, 403):
                    raise          # неверный ключ — второй адрес не поможет
        if j is None:
            raise last or RuntimeError("нет ответа")
        data = j.get("data") if isinstance(j.get("data"), dict) else j
        raw = data.get("amount")
        if raw is None:
            raw = data.get("balance", data.get("available"))
        v = float(raw)
        if b["value"] is None or abs(v - b["value"]) >= 0.01:
            log.info("Баланс Polza (ключ …%s): %.2f ₽", k[-4:], v)
        b.update(t=time.time(), value=v, error="")
    except Exception as e:
        if not b["error"]:
            log.warning("Не удалось получить баланс Polza (ключ …%s): %s", k[-4:], e)
        b.update(t=time.time(), error=str(e)[:120])
    return b


def qc_endpoint(st):
    """Адрес и ключ OpenAI-совместимого API для проверки и профилей: Polza или свой сервер."""
    base = (st.get("qc_base_url") or "").strip().rstrip("/") or API
    key = (st.get("qc_api_key") or "").strip()
    if not key and "polza.ai" in base:
        key = st.get("api_key") or ""
    return base, key


def _parse_json(text):
    text = re.sub(r"```(?:json)?", "", text or "")
    a, b = text.find("{"), text.rfind("}")
    if a < 0:
        raise ValueError("модель ответила не JSON: " + text[:200])
    body = text[a:b + 1] if b > a else text[a:]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return json.loads(_repair_json(text[a:]))


def _repair_json(s):
    """Типичные поломки JSON от языковых моделей: кавычки внутри строки без «\\» (размер 15", кнопка "Пуск"),
    переносы строк внутри строки, запятая перед } или ], ответ, обрезанный на середине."""
    out, stack, in_str, i, n = [], [], False, 0, len(s)
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                out.append(s[i:i + 2])
                i += 2
                continue
            if c == '"':
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                if j >= n or s[j] in ",:}]":      # кавычка закрывает строку
                    in_str = False
                    out.append(c)
                else:                            # кавычка внутри текста — экранируем
                    out.append('\\"')
            elif c == "\n":
                out.append("\\n")
            elif c == "\r":
                pass
            elif c == "\t":
                out.append("\\t")
            else:
                out.append(c)
        else:
            if c == '"':
                in_str = True
            elif c in "{[":
                stack.append("}" if c == "{" else "]")
            elif c in "}]":
                while out and out[-1].strip() == "":
                    out.pop()
                if out and out[-1] == ",":       # лишняя запятая перед закрывающей скобкой
                    out.pop()
                if stack:
                    stack.pop()
                out.append(c)
                if not stack:                    # объект закончился — дальше пояснения модели
                    break
                i += 1
                continue
            out.append(c)
        i += 1
    if in_str:                                   # ответ обрезан на середине строки
        out.append('"')
    tail = "".join(out).rstrip()
    tail = re.sub(r",\s*$", "", tail)
    tail = re.sub(r'(,|\{)\s*"[^"]*"\s*:?\s*$', r"\1", tail)   # оборванный ключ без значения
    tail = re.sub(r",\s*$", "", tail)
    return tail + "".join(reversed(stack))


_NO_REASONING = set()      # адреса API, которые не принимают параметр reasoning


def chat(st, model, system, content, trace, what, max_tokens=1500, reasoning=None, _retry=True):
    from ..services import payments
    with payments.call(KIND.get(what, what), model, trace) as oid:
        return _chat_paid(st, model, system, content, trace, what, max_tokens, reasoning, _retry, oid)


def _chat_paid(st, model, system, content, trace, what, max_tokens=1500, reasoning=None, _retry=True, paid_id=None):
    """Запрос к OpenAI-совместимому чату (Polza, vLLM, Ollama). Возвращает (разобранный JSON, стоимость ₽, секунды).
    reasoning: auto — как решит модель; none/minimal/low/medium/high — уровень «размышлений» (они оплачиваются как ответ).
    Расход пишется в trace (потом — в журнал расходов)."""
    tag = str(trace)
    base, key = qc_endpoint(st)
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    eff = (reasoning or "auto").strip().lower()
    if eff not in ("", "auto") and base not in _NO_REASONING:
        body["reasoning"] = {"effort": eff}
    # рассуждения расходуют тот же лимит, что и ответ: при «auto» и высоких уровнях даём запас, иначе JSON обрежется
    body["max_tokens"] = max_tokens if eff in ("none", "minimal") else max_tokens + (2500 if eff == "low" else 6000)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    t0 = time.time()
    r = None
    attempt = 0
    while attempt < 6:
        try:
            lim = throttle.limiter("chat", key or base)
            lim.acquire()
            with throttle.chat_slots:
                from ..services import payments
                payments.submitted()
                r = http.post(f"{base}/chat/completions", headers=headers, json=body, timeout=(20, 240))
        except requests.RequestException as e:
            attempt += 1
            log.warning("%s %s: модель недоступна (попытка %d/3): %s", tag, what, attempt, e)
            if not _not_sent(e):
                raise RuntimeError(f"{what}: связь оборвалась после отправки; автоматический повтор отключён") from e
            if attempt >= 3:
                payments.not_charged()
                raise RuntimeError(f"{what}: нет связи с моделью: {e}")
            time.sleep(8)
            continue
        if r.status_code == 400 and "reasoning" in body and "reason" in r.text.lower():
            log.warning("%s %s: API не принимает параметр reasoning — отправляю без него (%s)", tag, what, r.text[:200])
            _NO_REASONING.add(base)
            body.pop("reasoning")
            continue
        if r.status_code in (429, 503):
            lim.on_throttle(r.headers.get("Retry-After"))
        elif r.status_code < 400:
            lim.on_ok()
        if r.status_code == 429 and attempt < 5:
            attempt += 1
            log.warning("%s %s: HTTP %s (попытка %d/5)", tag, what, r.status_code, attempt)
            continue
        if r.status_code >= 400:
            if r.status_code < 500:
                payments.not_charged()
            log.error("%s %s: HTTP %s: %s", tag, what, r.status_code, "ответ скрыт" if what == "assistant" else r.text[:500])
            raise RuntimeError(f"{what}: HTTP {r.status_code}: {r.text[:300]}")
        break
    j = r.json()
    choice = (j.get("choices") or [{}])[0]
    msg = (choice.get("message") or {}).get("content")
    if isinstance(msg, list):
        msg = "".join(p.get("text", "") for p in msg if isinstance(p, dict))
    usage = j.get("usage") or {}
    cost = _num(usage.get("cost_rub")) or _num(usage.get("cost")) or _num(j.get("cost")) or 0.0
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    rt = int(((usage.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0)
    cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    secs = time.time() - t0
    payments.settle(paid_id, cost, {"prompt": pt, "completion": ct, "reasoning": rt, "cached": cached})
    trace.add(KIND.get(what, what), model, cost, {"prompt": pt, "completion": ct, "reasoning": rt, "cached": cached})
    log.info("%s %s: %.1f с · %.2f ₽ · токены: вход %d%s, ответ %d%s", tag, what, secs, cost, pt,
             f" (из кэша {cached})" if cached else "", ct, f" (из них рассуждения {rt})" if rt else "")
    if what != "assistant":
        log.debug("%s %s: ответ: %s", tag, what, (msg or "")[:3000])
    if not (msg or "").strip() and choice.get("finish_reason") == "length":
        raise RuntimeError(f"{what}: модель израсходовала лимит токенов на рассуждения и не дала ответ — "
                           "поставьте в настройках «Рассуждения» ниже")
    try:
        res = _parse_json(msg)
    except Exception as e:
        log.error("%s %s: модель ответила испорченным JSON (%s): %s", tag, what,
                  type(e).__name__ if what == "assistant" else e, "ответ скрыт" if what == "assistant" else (msg or "")[:3000])
        cut = choice.get("finish_reason") == "length"
        if _retry:      # один повтор: обрезанному ответу — вдвое больше лимит, иначе — та же просьба ещё раз
            log.warning("%s %s: повторяю запрос%s", tag, what, " с увеличенным лимитом ответа" if cut else "")
            retry_token = payments.retry_context.set(True)
            try:
                res, cost2, secs2 = chat(st, model, system, content, trace, what, max_tokens * 2 if cut else max_tokens,
                                         reasoning, _retry=False)
            finally:
                payments.retry_context.reset(retry_token)
            return res, cost + cost2, secs + secs2
        raise RuntimeError(f"{what}: модель {model} ответила испорченным JSON"
                           + (" — ответ обрезан по лимиту токенов" if cut else "")
                           + ", починить автоматически не удалось. Запустите ещё раз; если повторяется — смените модель"
                           f" ({e})") from e
    return res, cost, secs


# ───────── каталог моделей Polza ─────────

_catalogs = {"image": {"t": 0, "models": None, "error": ""}, "qc": {"t": 0, "models": None, "error": ""}}


def price_summary(pricing):
    """Короткое описание цены из блока pricing Polza (поля у разных моделей разные)."""
    if not isinstance(pricing, dict):
        return ""
    parts = []
    for k, v in pricing.items():
        n = _num(v)
        if n is None or n <= 0 or k == "currency":
            continue
        kl = k.lower()
        if "cache" in kl or "audio" in kl or "video" in kl:
            continue
        if "image" in kl and "million" not in kl:
            unit, prio = "₽/изобр.", 0
        elif "image" in kl:
            unit, prio = "₽/1M ток. изобр.", 1
        elif "request" in kl:
            unit, prio = "₽/запрос", 2
        elif "completion" in kl or "output" in kl:
            unit, prio = "₽/1M ток. вывод", 3
        elif "prompt" in kl or "input" in kl:
            continue
        else:
            unit, prio = k, 4
        parts.append((prio, f"{n:g} {unit}"))
    parts.sort()
    return " · ".join(p for _, p in parts[:2])


def _fetch_models_raw(kind="image", k=""):
    headers = {"accept-language": "ru"}
    if k:
        headers["Authorization"] = f"Bearer {k}"
    params = {"include_providers": "true"}
    if kind == "image":
        params["type"] = "image"
    r = http.get(f"{API}/models", params=params, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def image_models(force=False, kind="image", key=""):
    """kind=image — модели генерации; kind=qc — текстовые модели, принимающие картинки (для проверки)."""
    _catalog = _catalogs[kind]
    if not force and _catalog["models"] is not None and time.time() - _catalog["t"] < 600:
        return _catalog
    try:
        j = _fetch_models_raw(kind, key)
        items = j if isinstance(j, list) else (j.get("data") or [])
        out = []
        for m in items:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            arch = m.get("architecture") or {}
            if kind == "image" and m.get("type") and m["type"] != "image":
                continue
            if kind == "qc":
                outs = arch.get("output_modalities") or []
                if m.get("type") in ("image", "video", "audio", "embedding") or (outs and "text" not in outs):
                    continue
                if "image" not in (arch.get("input_modalities") or []):
                    continue
            provs = [{"name": p.get("name") or "", "price": price_summary(p.get("pricing")),
                      "moderated": bool(p.get("is_moderated"))}
                     for p in (m.get("providers") or []) if isinstance(p, dict) and p.get("name")]
            note, max_res = note_for(m["id"], m.get("name") or "", m.get("description") or "") if kind == "image" else ("", None)
            out.append({"id": m["id"], "name": m.get("name") or m["id"], "note": note, "max_res": max_res,
                        "refs": "image" in (arch.get("input_modalities") or []),
                        "price": price_summary((m.get("top_provider") or {}).get("pricing")),
                        "providers": provs, "created": m.get("created") or 0})
        out.sort(key=lambda x: x["name"].lower())
        _catalog.update(t=time.time(), models=out, error="")
        log.info("Каталог Polza (%s): %d моделей", "проверка" if kind == "qc" else "генерация", len(out))
    except Exception as e:
        log.exception("Не удалось загрузить каталог Polza (%s)", kind)
        _catalog.update(t=time.time(), error=f"Не удалось загрузить каталог Polza: {e}"[:300])
        if _catalog["models"] is None:
            _catalog["models"] = []
    return _catalog

