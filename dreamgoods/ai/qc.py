"""ИИ-проверка кадра: технический фильтр → сверка с референсами (только причины брака) → по желанию подсчёт.
Решение принимает код: кадр принят, если причин брака нет."""
import hashlib
import io
import re

from PIL import Image, ImageFilter, ImageOps, ImageStat
from sqlalchemy.exc import IntegrityError

from .. import db
from ..core.logs import log, mb
from ..db.models import SpecCache
from .images import jpeg_data_url
from .polza import chat
from .views import VIEW_RU, filter_checklist, select_refs, shot_view


def _aspect_value(a):
    try:
        w, h = str(a).split(":")
        return float(w) / float(h)
    except Exception:
        return None


def tech_check(img, st, tag=""):
    """Слой 1: быстрые проверки кодом. Возвращает (список проблем, сведения)."""
    from .images import DECODE_SLOTS
    with DECODE_SLOTS:
        return _tech_check(img, st, tag)


def _tech_check(img, st, tag=""):
    issues = []
    with Image.open(io.BytesIO(img)) as im:
        w, h = im.size
        g = ImageOps.exif_transpose(im).convert("L")
    min_side = int(st.get("qc_min_side") or 0)
    if min_side and min(w, h) < min_side:
        issues.append(f"низкое разрешение {w}×{h}")
    a = _aspect_value(st.get("aspect"))
    if a and abs(w / h - a) / a > 0.04:
        issues.append(f"пропорции {w}×{h} не соответствуют {st.get('aspect')}")
    g.thumbnail((1024, 1024))
    if ImageStat.Stat(g).stddev[0] < 4:
        issues.append("почти пустое изображение")
    # резкость только записываем: порог размытия без калибровки на эталоне ненадёжен, размытие оценивает vision-LLM
    sharp = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).var[0] / max(ImageStat.Stat(g).var[0], 1) * 100
    log.info("%s техпроверка: %d×%d, резкость %.1f — %s", tag, w, h, sharp, "; ".join(issues) or "ок")
    return issues, {"w": w, "h": h, "sharp": round(sharp, 1)}


from ..core.moderation import PROHIBITED_FIELD, PROHIBITED_RULE

QC_SYSTEM = """You are a quality-control inspector for marketplace product photos of ANY product category.
Compare the GENERATED image with the REFERENCE photos of the real product and the TASK given to the image generator.

List ONLY defects that make the photo unusable for a product card. Check, in this order:
1. Product identity: the same product as in the references — shape, silhouette, proportions, color, material and every visible
   element (see the CHECKLIST). A missing or added element counts; fastenings and decor must be on the same side.
2. Quantity: the number of product units matches the TASK; no duplicated, merged, cut or missing units.
3. People, if present: as many people as the TASK requires; each person has one head, two arms, two legs and five fingers on every
   visible hand; no extra, merged, disconnected or floating limbs; the product is worn or held naturally.
4. Text and logos: not distorted, not invented, no garbled letters.
5. Task: shot type, background and framing as in the TASK; no watermarks, captions, collages or grids; no obvious generation artifacts.
6. Prohibited content — see the rule below; it is always a defect.

MISSING DETAILS — the most common false alarm, follow strictly:
- The references show the product from several sides; the generated image shows only ONE side. Details that are on the other side
  of the product are NOT expected to be visible.
- Report a detail as missing ONLY if the exact part of the product where it must be is clearly visible in the generated image,
  large enough to see it, and the detail is not there. If that part faces away from the camera, is cropped, covered by something,
  in shadow or too small — do NOT report it.
- The CHECKLIST lists what the product has, NOT what every photo must show.

Do NOT report:
- details hidden by the angle, distance, framing, shadow or pose (e.g. a back seam or a zip on the inner side in an outer side view,
  the bottom of the sole in a side view, fine details of a product that is small in a wide shot);
- minor differences a customer would not notice (texture density, slight proportion or shade differences, lighting);
- price stickers, tags and labels visible in the references;
- background, scene, person and pose choices allowed by the TASK.

""" + PROHIBITED_RULE + """

Reply with ONLY this JSON, nothing else:
{"defects": ["короткая причина брака по-русски", "..."], """ + PROHIBITED_FIELD + """}
An empty defects list and an empty prohibited string mean the photo is good."""

STRICTNESS_RULES = {
    "strict": """

STRICTNESS: STRICT. Also report small but visible deviations from the references that a careful customer could notice when
comparing: a different shade, texture or pattern scale, stitching, small decor, slightly different proportions or hardware color.
The rules about details hidden by the angle still apply.""",
    "normal": "",
    "critical": """

STRICTNESS: ONLY CRITICAL. Report ONLY defects that make it a different or broken product or photo: a different product type,
clearly wrong color or material, a missing or extra MAJOR part (strap, fastening, heel, handle, sleeve), a wrong number of units,
anatomy errors (extra or missing limbs or fingers, merged bodies), distorted or invented text and logos, watermarks, collages.
Do NOT report anything else: small decor, stitching, texture, slight shape or shade differences, minor artifacts.""",
}


def qc_system(st):
    return QC_SYSTEM + STRICTNESS_RULES.get(st.get("qc_strictness") or "normal", "")


def vlm_check(st, task, refs, img, trace):
    """Слой 2: сверка с исходниками на vision-LLM через OpenAI-совместимый API (Polza, vLLM, Ollama).
    Порядок частей: сначала неизменное для артикула (чек-лист, референсы), в конце — задание и кадр.
    Одинаковое начало запроса модель может закэшировать и взять дешевле."""
    tag = str(trace)
    view = shot_view(task)
    refs = [r if isinstance(r, dict) else {"data": r, "view": "", "note": ""} for r in refs]
    chosen = select_refs(refs, view, 6)
    checklist = filter_checklist(st.get("qc_checklist") or "", view)
    content = [{"type": "text", "text": "CHECKLIST — what the product has; check an item ONLY if the part of the product where it is "
                "located is clearly visible in the generated image, never report it as missing otherwise:\n"
                + checklist + "\n\nREFERENCE PHOTOS of the real product (ground truth), each with the side it shows:"}]
    labels = {"same": "SAME SIDE AS THE SHOT — compare details with this one",
              "overview": "overview of the product",
              "other": "OTHER SIDE — details visible only here are HIDDEN in the shot, never report them as missing",
              "": ""}
    for n, r in enumerate(chosen, 1):
        desc = f"Reference {n}" + (f" — view: {r['view']}" if r.get("view") else "") \
            + (f"; visible here: {r['note']}" if r.get("note") else "") + (f". {labels[r['tag']]}" if r.get("tag") else "") + ":"
        content.append({"type": "text", "text": desc})
        content.append({"type": "image_url", "image_url": {"url": r.get("url") or jpeg_data_url(r["data"], 768)}})
    shot = (f"\n\nThe generated image is a {view.upper()} shot of the product. Judge only the side of the product that faces "
            f"the camera; details that exist only on other sides are hidden in this shot and are not defects.") if view else ""
    content.append({"type": "text", "text": "TASK given to the image generator:\n" + task + shot + "\n\nGENERATED IMAGE to inspect:"})
    # кадр целиком в высоком разрешении: нарезка на части разрезала товар, и модель «не находила» детали на краях кусков
    content.append({"type": "image_url", "image_url": {"url": img if isinstance(img, str) else
                                                       jpeg_data_url(img, int(st.get("qc_image_side") or 2048))}})
    size = sum(len(c["image_url"]["url"]) for c in content if c["type"] == "image_url")
    log.info("%s → сверка: %s · строгость: %s · ракурс кадра: %s · референсы: %s · запрос %s", tag, st.get("qc_model"),
             {"strict": "строго", "critical": "только критичное"}.get(st.get("qc_strictness"), "обычно"),
             VIEW_RU.get(view, "не определён"),
             ", ".join(f"{VIEW_RU.get(r.get('view'), r.get('view') or '?')}{'*' if r.get('tag') == 'same' else ''}" for r in chosen),
             mb(size))
    res, cost, secs = chat(st, st.get("qc_model"), qc_system(st), content, trace, "сверка", 1500, st.get("qc_reasoning"))
    reasons = []
    if not isinstance(res, dict) or not isinstance(res.get("defects"), list):
        raise ValueError("ИИ-проверка вернула неверный ответ: нужен список defects")
    raw = res["defects"]
    for item in raw:
        if not isinstance(item, (str, dict)) or (isinstance(item, dict) and not isinstance(item.get("text", item.get("reason")), str)):
            raise ValueError("ИИ-проверка вернула неверное описание дефекта")
    if "prohibited" in res and not isinstance(res["prohibited"], str):
        raise ValueError("ИИ-проверка вернула неверное поле prohibited")
    if isinstance(raw, str):        # модель вернула строку вместо списка
        raw = [x for x in re.split(r";\s*|\n+", raw) if x.strip()]
    for x in raw if isinstance(raw, list) else []:
        t = (x.get("text") or x.get("reason") or "") if isinstance(x, dict) else str(x)
        if t.strip():
            reasons.append(t.strip())
    prohibited = str(res.get("prohibited") or "").strip()
    if prohibited.lower() in ("none", "нет", "-", "—", "no", "null"):
        prohibited = ""
    if prohibited:
        reasons.insert(0, f"запрещённое содержание: {prohibited}")
    log.info("%s сверка: %s", tag, ("БРАК — " + "; ".join(reasons)) if reasons else "без замечаний")
    return {"reasons": reasons, "cost": cost, "prohibited": prohibited}


SPEC_PROMPT = """You read a task for an AI image generator (a product photo for a marketplace, any category) and write down
what must be COUNTABLE in the resulting image, so that an inspector can verify it.

Rules:
- people: exact number of people that must be visible; 0 for a product-only shot; null if the task does not say.
- entities: WHOLE product units and other separate countable objects with an exact expected number
  (e.g. {"name":"boot","expected":2}, {"name":"cream jar","expected":1}, {"name":"hand","expected":1}).
  Use short English nouns. Include the product itself. Do not include background details.
  NEVER include parts or details of the product (zip, buckle, toe cap, heel, sole, strap, button, lace, stone, seam, logo, cap, pocket):
  they may be hidden in a given angle and are checked elsewhere.
  If the number is not determined by the task, do not include the entity.
- forbidden: things that must NOT appear (e.g. "people", "text", "second product", "price tag").

Reply with ONLY one JSON object, no markdown:
{"people": 0, "entities": [{"name": "...", "expected": 1}], "forbidden": ["..."]}"""

COUNT_PROMPT = """You are inspecting an AI-generated product photo for counting and anatomy errors.
AI images very often contain: an extra or missing product unit, a third leg or arm, six fingers, two legs merged into one,
a limb growing from the wrong place or ending in nothing, a duplicated person or head, an object floating without support.

Ignore beauty, style and composition. Be literal: report exactly what is drawn, even if it is impossible.
You get the full image in high resolution. First describe, then count.

Reply with ONLY one JSON object, no markdown:
{"people": [{"description": "who and where; describe every visible limb: where it starts and where it ends",
             "heads": 1, "arms": 2, "hands": 2, "legs": 2, "feet": 2,
             "fingers_per_visible_hand": [5, 5]}],
 "entities": [{"name": "<as requested>", "count": 0, "description": "where each one is"}],
 "anomalies": ["each impossible or broken thing you see: extra/merged/disconnected limbs, duplicated objects, floating objects; empty list if none"],
 "problems": "найденные ошибки по-русски, пустая строка если их нет"}
Count only what is visible; a limb cut by the frame edge still counts as one limb. For fingers list only hands where all fingers are clearly visible."""


def task_spec(st, task, trace):
    """Что должно быть в кадре — модель читает промпт. Кэш в PostgreSQL: за один промпт платим один раз."""
    model = (st.get("qc_count_model") or "").strip() or st.get("qc_model")
    h = hashlib.sha256((model + "\n" + task).encode("utf-8")).hexdigest()
    with db.session() as s:
        hit = s.get(SpecCache, h)
        if hit:
            return hit.data, 0.0
    tag = str(trace)
    res, cost, secs = chat(st, model, SPEC_PROMPT, "TASK:\n" + task, trace, "ожидания", 800, "none")
    if not isinstance(res, dict) or not all(k in res for k in ("people", "entities", "forbidden")):
        raise ValueError("ИИ вернул неполное описание ожидаемых объектов")
    if not isinstance(res["entities"], list) or not isinstance(res["forbidden"], list):
        raise ValueError("ИИ вернул неверные списки ожидаемых объектов")
    if res["people"] is not None and (type(res["people"]) is not int or res["people"] < 0):
        raise ValueError("ИИ вернул неверное число людей")
    if any(not isinstance(e, dict) or not isinstance(e.get("name"), str) or not e["name"].strip()
           or type(e.get("expected")) is not int or e["expected"] < 0 for e in res["entities"]):
        raise ValueError("ИИ вернул неверное описание ожидаемого объекта")
    if any(not isinstance(x, str) for x in res["forbidden"]):
        raise ValueError("ИИ вернул неверный список запрещённых объектов")
    people = _int(res.get("people"))
    ents = []
    for e in res.get("entities") or []:
        if isinstance(e, dict) and e.get("name") and _int(e.get("expected")) is not None:
            ents.append({"name": str(e["name"]).strip().lower()[:40], "expected": _int(e["expected"])})
    parts = re.compile(r"\b(zip|zipper|buckle|toe|cap|heel|sole|strap|button|lace|stone|rhinestone|seam|logo|pocket|"
                       r"handle|clasp|chain|stitch|panel|insole|tag|label)s?\b")
    dropped = [e["name"] for e in ents if parts.search(e["name"])]
    ents = [e for e in ents if not parts.search(e["name"])]
    if dropped:
        log.info("%s ожидания: детали товара не считаем — %s", tag, ", ".join(dropped))
    spec = {"people": people, "entities": ents[:8],
            "forbidden": [str(x)[:60] for x in (res.get("forbidden") or [])][:10]}
    log.info("%s ожидания по заданию (%.1f с, %.2f ₽): людей %s · %s%s", tag, secs, cost,
             "?" if people is None else people, ", ".join(f"{e['name']} ×{e['expected']}" for e in spec["entities"]) or "—",
             f" · запрещено: {', '.join(spec['forbidden'])}" if spec["forbidden"] else "")
    with db.session() as s:
        try:
            with s.begin_nested():
                if not s.get(SpecCache, h):
                    s.add(SpecCache(hash=h, data=spec))
                    s.flush()
        except IntegrityError:
            pass  # другой воркер успел сохранить те же ожидания
    return spec, cost


def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _same(a, b):
    a, b = a.lower().rstrip("s"), b.lower().rstrip("s")
    return a == b or a in b or b in a


def count_check(st, task, img, trace):
    """Подсчёт объектов и анатомии для любой категории. Решение по числам принимает код."""
    spec, cost = task_spec(st, task, trace)
    tag = str(trace)
    model = (st.get("qc_count_model") or "").strip() or st.get("qc_model")
    names = [e["name"] for e in spec["entities"]]
    ask = ("Count these entities (use exactly these names): " + ", ".join(names)) if names else \
        "Count the product units visible in the image (entity name: product)."
    # увеличенные четверти нужны, чтобы разглядеть пальцы и ноги; для предметных кадров хватает общего вида
    content = [{"type": "text", "text": ask + "\n\nIMAGE:"},
               {"type": "image_url", "image_url": {"url": img if isinstance(img, str) else
                                                   jpeg_data_url(img, int(st.get("qc_image_side") or 2048))}}]
    log.info("%s → подсчёт: %s · считаем: людей, части тела%s · %s · рассуждения %s", tag, model,
             (", " + ", ".join(names)) if names else "", "кадр целиком",
             st.get("qc_count_reasoning") or "auto")
    res, c2, secs = chat(st, model, COUNT_PROMPT, content, trace, "подсчёт", 1500, st.get("qc_count_reasoning"))
    cost += c2
    if not isinstance(res, dict) or not all(isinstance(res.get(k), list) for k in ("people", "entities", "anomalies")):
        raise ValueError("ИИ-подсчёт вернул неполный ответ")
    if not isinstance(res.get("problems"), str):
        raise ValueError("ИИ-подсчёт вернул неверное поле problems")
    if any(not isinstance(p, dict) or not all(type(p.get(k)) is int and p[k] >= 0 for k in ("heads", "arms", "hands", "legs", "feet")) for p in res["people"]):
        raise ValueError("ИИ-подсчёт вернул неверные числа частей тела")
    if any(not isinstance(p.get("fingers_per_visible_hand"), list)
           or any(type(n) is not int or n < 0 for n in p["fingers_per_visible_hand"]) for p in res["people"]):
        raise ValueError("ИИ-подсчёт вернул неверные числа пальцев")
    if any(not isinstance(a, str) for a in res["anomalies"]):
        raise ValueError("ИИ-подсчёт вернул неверный список аномалий")
    if any(not isinstance(e, dict) or not isinstance(e.get("name"), str) or not e["name"].strip() or type(e.get("count")) is not int or e["count"] < 0 for e in res["entities"]):
        raise ValueError("ИИ-подсчёт вернул неверное число объектов")
    if any(not any(_same(e["name"], name) for e in res["entities"]) for name in names):
        raise ValueError("ИИ-подсчёт пропустил запрошенный объект")

    issues = []
    people = [p for p in (res.get("people") or []) if isinstance(p, dict)]
    # 1) число людей по заданию
    if spec["people"] is not None and len(people) != spec["people"]:
        issues.append(f"людей {len(people)} вместо {spec['people']}")
    # 2) универсальные правила анатомии — для любой категории
    limits = {"heads": (1, "голов"), "arms": (2, "рук"), "hands": (2, "кистей"), "legs": (2, "ног"), "feet": (2, "стоп")}
    for n, p in enumerate(people, 1):
        who = f"человек {n}: " if len(people) > 1 else ""
        for k, (mx, ru) in limits.items():
            v = _int(p.get(k))
            if v is not None and v > mx:
                issues.append(f"{who}{ru} {v} (максимум {mx})")
        legs, feet = _int(p.get("legs")), _int(p.get("feet"))
        if legs is not None and feet is not None and feet > legs:
            issues.append(f"{who}стоп {feet} при {legs} ногах")
        for f in p.get("fingers_per_visible_hand") or []:
            f = _int(f)
            if f is not None and f > 5:
                issues.append(f"{who}{f} пальцев на руке")
    # 3) количество товара и ключевых объектов
    got_ents = [e for e in (res.get("entities") or []) if isinstance(e, dict)]
    ent_rows = []
    for e in spec["entities"]:
        m = next((g for g in got_ents if _same(str(g.get("name", "")), e["name"])), None)
        got = _int(m.get("count")) if m else None
        ent_rows.append({"name": e["name"], "got": got, "expected": e["expected"]})
        if got is not None and got != e["expected"]:
            issues.append(f"{e['name']}: {got} вместо {e['expected']}")
    # 4) явные аномалии, которые модель назвала сама
    anomalies = [str(a).strip() for a in (res.get("anomalies") or []) if str(a).strip()]
    issues += [f"аномалия: {a}" for a in anomalies[:4]]
    if issues and res.get("problems"):
        issues.append(str(res["problems"]).strip())

    log.info("%s подсчёт за %.1f с: людей %d%s%s · %.2f ₽ — %s", tag, secs, len(people),
             "".join(f" [{', '.join(f'{k} {p.get(k)}' for k in ('heads', 'arms', 'legs', 'feet') if p.get(k) is not None)}]"
                     for p in people),
             "".join(f" · {r['name']} {r['got']}/{r['expected']}" for r in ent_rows), cost, "; ".join(issues) or "ок")

    fix = []
    if spec["people"] is not None:
        fix.append(f"exactly {spec['people']} person(s)" if spec["people"] else "no people")
    if people or spec["people"]:
        fix.append("correct human anatomy: no extra, duplicated, merged or disconnected limbs; "
                   "never more than two arms and two legs per person; exactly five fingers on every visible hand")
    fix += [f"exactly {e['expected']} {e['name']}" for e in spec["entities"]]
    return {"issues": issues, "cost": cost, "fix": "; ".join(fix),
            "counts": {"people": [len(people), spec["people"]], "entities": ent_rows,
                       "body": [{k: p.get(k) for k in ("heads", "arms", "legs", "feet", "fingers_per_visible_hand")}
                                for p in people]}}


def prepare(img, st, tag=""):
    """Всё, что нужно проверке от картинки: техпроверка и JPEG для модели. Дальше оригинал (до десятков МБ при 4K)
    можно не держать в памяти, пока идёт запрос к модели проверки."""
    issues, info = tech_check(img, st, tag)
    return {"issues": issues, "info": info, "url": jpeg_data_url(img, int(st.get("qc_image_side") or 2048))}


def run_qc(st, task, refs, img, trace):
    """Проверка кадра: технический фильтр → одна сверка (только причины брака) → по желанию отдельный подсчёт.
    Кадр принят, если причин брака нет. img — байты картинки или результат prepare()."""
    tag = str(trace)
    if not isinstance(img, dict):
        img = prepare(img, st, tag)
    issues, info = img["issues"], img["info"]
    img = img["url"]
    prohibited = ""
    if issues and st.get("qc_cascade", True):
        log.info("%s каскад: техпроверка провалена — модель не вызываю", tag)
        reasons, cost, counts = list(issues), 0.0, None
    else:
        res = vlm_check(st, task, refs, img, trace)
        reasons, cost, counts = issues + res["reasons"], res["cost"], None
        prohibited = res.get("prohibited") or ""
        if st.get("qc_count") and not (reasons and st.get("qc_cascade", True)):
            c = count_check(st, task, img, trace)
            cost += c["cost"]
            counts = c["counts"]
            reasons += c["issues"]
    ok = not reasons
    score = round(1 / (1 + len(reasons)), 2)      # для выбора лучшей из неудачных попыток: меньше причин — лучше
    log.info("%s итог проверки: %s%s · %.2f ₽", tag, "ПРИНЯТ" if ok else "БРАК",
             "" if ok else " — " + "; ".join(reasons), cost)
    return {"pass": ok, "scores": {}, "min": score, "defects": "; ".join(reasons), "fix": "; ".join(reasons),
            "tech": issues, "info": info, "cost": cost, "qc_model": st.get("qc_model"), "counts": counts,
            "prohibited": prohibited}


def correction(prompt, fix):
    return (prompt + "\n\nIMPORTANT CORRECTION: a previous generation of this exact shot was rejected by quality control "
            f"for these reasons (in Russian): {fix}. Fix them and keep everything else as described above.")

