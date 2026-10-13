"""Ракурсы: с какой стороны показан товар на кадре и на референсах; подбор референсов той же стороны для проверки."""
import re

from ..core.logs import log
from .images import jpeg_data_url
from .polza import chat

# ───────── ракурсы ─────────
# Модель сравнивала кадр «сбоку» с референсом «сзади» и находила «нет молнии». Теперь код знает ракурс кадра
# (из задания) и ракурс каждого референса (ИИ подписывает один раз) и даёт на сверку фото той же стороны.

VIEWS = ("front", "back", "outer side", "inner side", "side", "three-quarter front", "three-quarter back", "top", "sole",
         "detail", "pair", "worn", "packaging")
_VIEW_RE = [
    ("three-quarter back", r"three[- ]quarters? back|3/4 back|back three[- ]quarter|over (her|his|the) shoulder"),
    ("three-quarter front", r"three[- ]quarters?|3/4"),
    ("sole", r"\bsole view|\bbottom view|underside|from below|outsole view|upside down"),
    ("top", r"\btop view|from above|overhead|top-down|flat[- ]?lay|bird'?s[- ]eye"),
    ("inner side", r"inner side view|inside view|medial|\binner side\b"),
    ("outer side", r"outer side view|outside view|lateral|\bouter side\b"),
    ("back", r"\bback view|\brear view|from behind|\bback\b"),
    ("side", r"\bside view|\bprofile\b|\bside\b"),
    ("front", r"\bfront view|\bfrom the front|\bfront\b|facing the camera|toward the camera"),
    ("detail", r"close-?up of (the|a) (detail|part)|macro|detail shot"),
]
NEIGHBORS = {
    "front": {"front", "three-quarter front"},
    "three-quarter front": {"three-quarter front", "front", "side", "outer side", "inner side"},
    "back": {"back", "three-quarter back"},
    "three-quarter back": {"three-quarter back", "back", "side", "outer side", "inner side"},
    "outer side": {"outer side", "side", "three-quarter front", "three-quarter back"},
    "inner side": {"inner side", "side", "three-quarter front", "three-quarter back"},
    "side": {"side", "outer side", "inner side", "three-quarter front", "three-quarter back"},
    "top": {"top", "front"},
    "sole": {"sole"},
    "detail": {"detail"},
}
VIEW_RU = {"front": "спереди", "back": "сзади", "outer side": "внешняя сторона", "inner side": "внутренняя сторона",
           "side": "сбоку", "three-quarter front": "три четверти спереди", "three-quarter back": "три четверти сзади",
           "top": "сверху", "sole": "подошва/низ", "detail": "деталь", "pair": "пара/общий вид", "worn": "на человеке",
           "packaging": "упаковка"}


def view_of(text):
    """Канонический ракурс по тексту (фраза «Shot: …» задания кадра)."""
    t = (text or "").lower()
    for name, rx in _VIEW_RE:
        if re.search(rx, t):
            return name
    return ""


def views_in(text):
    """Все ракурсы, упомянутые в тексте. Совпавший фрагмент вырезается, чтобы «inner side» не засчитывался ещё и как «side»."""
    t, found = (text or "").lower(), set()
    for name, rx in _VIEW_RE:
        if re.search(rx, t):
            found.add(name)
            t = re.sub(rx, " ", t)
    return found


def shot_view(task):
    """Ракурс кадра из фразы «Shot: …»; если её нет (промпт переписан вручную) — из конца промпта без хвоста про качество."""
    m = re.findall(r"shot:\s*([^.]*)", task or "", re.I)
    if m:
        return view_of(m[-1])
    body = re.split(r"photorealistic, high resolution", task or "", flags=re.I)[0]
    for sentence in reversed([x for x in re.split(r"[.!?\n]+", body) if x.strip()][-3:]):
        v = view_of(sentence)
        if v:
            return v
    return ""


VIEW_PROMPT = """You get several photos of ONE product (one SKU). For each photo say from which side the product is shown
and which notable details are visible in that photo.
view — exactly one of: front, back, outer side, inner side, side, three-quarter front, three-quarter back, top, sole, detail,
pair, worn, packaging.
- inner side = the side that faces the other item of a pair (for shoes: toward the other leg); outer side = the opposite.
  If you cannot tell inner from outer, use "side".
- pair = both items of a pair together; worn = the product on a person; detail = a close-up of one part.
shows — short English list of notable details visible in this photo (fastenings, decor, sole, logo…), or "".
Reply with ONLY one JSON object, no markdown: {"photos": [{"id": 1, "view": "...", "shows": "..."}]}"""


def classify_views(st, images, trace):
    """images: [bytes]. Возвращает [(view, shows)] в том же порядке. Один запрос на все фото, без рассуждений."""
    content = [{"type": "text", "text": "Photos of the product:"}]
    for n, data in enumerate(images, 1):
        content.append({"type": "text", "text": f"Photo {n}:"})
        content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(data, 768)}})
    res, cost, secs = chat(st, st.get("qc_model"), VIEW_PROMPT, content, trace, "ракурсы", 1500, "none")
    got = {}
    for ph in res.get("photos") or []:
        try:
            got[int(ph.get("id"))] = ph
        except (TypeError, ValueError, AttributeError):
            continue
    out = []
    for n in range(1, len(images) + 1):
        ph = got.get(n) or {}
        v = str(ph.get("view") or "").strip().lower()
        out.append((v if v in VIEWS else view_of(v) or "side", str(ph.get("shows") or "")[:400]))
    log.info("%s ракурсы референсов (%.1f с, %.2f ₽): %s", trace, secs, cost, ", ".join(VIEW_RU.get(v, v) for v, _ in out))
    return out


def select_refs(refs, view, k=6):
    """refs: [{data, view, note}]. Сначала фото той же и соседней стороны, затем общий вид, затем немного других сторон."""
    if not view or view not in NEIGHBORS:
        return [dict(r, tag="") for r in refs[:k]]
    near = NEIGHBORS[view]
    same = [r for r in refs if r.get("view") in near]
    overview = [r for r in refs if r.get("view") in ("pair", "worn", "")]
    other = [r for r in refs if r not in same and r not in overview and r.get("view") != "packaging"]
    out = [dict(r, tag="same") for r in same[:4]]
    out += [dict(r, tag="overview") for r in overview[:max(1, k - len(out) - 2)]]
    out += [dict(r, tag="other") for r in other[:min(2, max(0, k - len(out)))]]
    return out[:k] or [dict(r, tag="") for r in refs[:k]]


def filter_checklist(text, view):
    """Убирает пункты вида «… — visible only in back views», если ракурс кадра другой (решает код, а не модель)."""
    if not view or view not in NEIGHBORS:
        return text
    near = NEIGHBORS[view] | {view}
    out, dropped = [], []
    for line in (text or "").splitlines():
        low = line.lower()
        m = re.search(r"(visible|seen|only)\b.*", low)
        if m:
            mentioned = views_in(m.group(0))
            if mentioned and not (mentioned & near):
                dropped.append(line.strip(" -"))
                continue
        out.append(line)
    if dropped:
        log.debug("чек-лист: для ракурса «%s» убраны пункты: %s", view, "; ".join(dropped))
    return "\n".join(out)
