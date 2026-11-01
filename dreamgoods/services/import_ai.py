"""Дополнительные проходы ИИ при раскладке загрузки (после общей сортировки по листам).

1. Дочитывание бирок: фото бирок и фото товара с наклейкой (подошва, стелька), где артикул не прочитан на маленькой
   картинке листа, отправляются ещё раз крупно (1280 px) — только ради текста.
2. Проверка групп: каждая группа с несколькими фото товара показывается модели отдельно и крупнее, с вопросом
   «это один товар?». Если нет — модель делит её на товары. На листе из 20 фото модель легко принимает похожие
   товары за один; сравнение внутри одной группы намного точнее.
"""
from concurrent.futures import ThreadPoolExecutor

from ..ai.images import jpeg_data_url
from ..ai.polza import chat
from ..core import storage
from ..core.logs import log

LABEL_SIDE, VERIFY_SIDE = 1280, 640
LABEL_BATCH, VERIFY_MAX = 4, 16
PARALLEL = 4

LABEL_PROMPT = """You read printed text on product labels for a marketplace seller. Each image shows a label, tag, sticker or
a product part with a sticker on it (often a size/article sticker on a shoe sole or insole). Read carefully, zoom into
small stickers. For EACH image return:
- codes: EVERY code printed (article/model code, color code, size), exactly as printed, except barcode digits;
- article: the model/article code (letters and/or digits with separators, e.g. "BX096-2", "K-1205"), NOT the size,
  NOT the price, NOT the barcode digits; "" if there is no such code;
- text: other useful printed info briefly (brand, size, color, composition); "" if none.
Reply with ONLY one JSON object, no markdown:
{"photos":[{"id":1,"article":"","codes":[],"text":""}]}"""

VERIFY_PROMPT = """You check one group of a seller's photos that an automatic sorter put together as ONE product.
Photos are in shooting order; each is preceded by its id and its role (product / label / packaging).
Decide which photos show the SAME physical product. Compare the model carefully: type, silhouette, shape of toe and
heel, sole, height, fastening (zip, laces, buckles), decor, material and texture, color. Different angles, close-ups
of parts (sole, heel, lining, zip) and the product's own label are the SAME product. Different model, color or type
is a DIFFERENT product, even if similar.
Give each photo a letter: "A" for the first product, "B" for the next one, and so on. A label/packaging photo gets the
letter of the product it belongs to (the sticker is on it, or it was photographed right before/after that product).
If all photos are one product, give all of them "A".
Reply with ONLY one JSON object, no markdown:
{"photos":[{"id":1,"product":"A"}],"reason":"<one short sentence in Russian: why split, or empty>"}"""


def _ask(st, model, prompt, content, trace, what, max_tokens):
    try:
        return chat(st, model, prompt, content, trace, what, max_tokens, "none")
    except Exception as e:             # проход необязательный: при ошибке остаётся результат общей сортировки
        log.warning("%s %s: %s", trace, what, e)
        return {}, 0.0, 0.0


def read_labels(st, model, rows, trace):
    """rows: фото, где нужно дочитать бирку → {id: {article, codes, text}}, стоимость."""
    batches = [rows[i:i + LABEL_BATCH] for i in range(0, len(rows), LABEL_BATCH)]

    def one(batch):
        content = []
        for r in batch:
            content.append({"type": "text", "text": f"Image {r['id']}:"})
            content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(storage.get(r["key"]), LABEL_SIDE)}})
        return _ask(st, model, LABEL_PROMPT, content, trace, "бирки крупно", 1200)

    out, cost = {}, 0.0
    with ThreadPoolExecutor(PARALLEL) as pool:
        for res, c, _ in pool.map(one, batches):
            cost += c
            for ph in (res or {}).get("photos") or []:
                try:
                    out[int(ph.get("id"))] = ph
                except (TypeError, ValueError, AttributeError):
                    pass
    return out, cost


def verify_groups(st, model, groups, trace, rules_text=""):
    """groups: [[row, …], …] → для каждой группы {id: буква} (или {} — без изменений), причина; общая стоимость."""

    def one(g):
        shown = [r for r in g if r["role"] != "junk"][:VERIFY_MAX]
        content = [{"type": "text", "text": rules_text}] if rules_text else []
        for r in shown:
            content.append({"type": "text", "text": f"Photo {r['id']} ({r['role']}):"})
            content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(storage.get(r["key"]), VERIFY_SIDE)}})
        res, c, _ = _ask(st, model, VERIFY_PROMPT, content, trace, "проверка группы", 800)
        letters = {}
        for ph in (res or {}).get("photos") or []:
            try:
                letters[int(ph.get("id"))] = str(ph.get("product") or "A").strip().upper()[:3] or "A"
            except (TypeError, ValueError, AttributeError):
                pass
        return letters, str((res or {}).get("reason") or "")[:200], c

    out, cost = [], 0.0
    with ThreadPoolExecutor(PARALLEL) as pool:
        for letters, reason, c in pool.map(one, groups):
            cost += c
            out.append((letters, reason))
    return out, cost


def split_by_letters(g, letters):
    """Группа + буквы от проверки → части по буквам (в порядке съёмки). Фото без буквы — к соседнему фото с буквой."""
    if len(set(letters.values())) < 2:
        return [g]
    seq, last = [], None
    for r in g:
        L = letters.get(r["id"])
        if L is None:
            L = last
        seq.append(L)
        last = L if L is not None else last
    first = next((x for x in seq if x is not None), "A")
    seq = [x if x is not None else first for x in seq]
    parts, order = {}, []
    for r, L in zip(g, seq):
        if L not in parts:
            parts[L] = []
            order.append(L)
        parts[L].append(r)
    out = [parts[L] for L in order]
    # часть без фото товара (одни бирки) — к соседней части
    res = []
    for p in out:
        if res and not any(x["role"] == "product" for x in p):
            res[-1].extend(p)
        else:
            res.append(p)
    if len(res) > 1 and not any(x["role"] == "product" for x in res[0]):
        res[1] = res[0] + res[1]
        res.pop(0)
    return res
