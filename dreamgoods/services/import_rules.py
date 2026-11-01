"""Номенклатура загрузки: правила, по которым фото раскладываются по товарам.

Продавец один раз описывает, как он снимает и как устроены его бирки: порядок «товар — бирка», примерное число фото
и бирок на товар, образец артикула, что считать разными товарами и что игнорировать. Правила хранятся в настройках
проекта (settings["import_rules"]) и подставляются в следующую загрузку.

Правила работают двумя способами:
1. как подсказка ИИ — блок в запросе на раскладку (prompt_section);
2. как проверки после ответа ИИ — без модели и без денег: выбор артикула по образцу из всех кодов на бирке,
   деление групп по биркам в заданном порядке съёмки, деление по виду товара (тип и цвет), предупреждения
   о слишком больших группах, упаковка в «не использовать».
"""
import re

ORDERS = ("auto", "label_after", "label_before", "no_label")
IGNORE = ("price", "barcode", "size", "packaging")

DEFAULTS = {
    "order": "auto",              # auto — определит ИИ; label_after — сначала товар, потом бирка; label_before — наоборот
    "photos_per_product": 0,      # примерно фото на товар; 0 — не знаю
    "labels_per_product": -1,     # бирок (фото бирок) на товар: -1 — не знаю, 0 — нет, 1, 2…
    "article_example": "",        # образец артикула, например BX096-2
    "colors_separate": True,      # разные цвета одной модели — разные товары
    "sizes_together": True,       # разные размеры одной модели — один товар
    "ignore": ["price", "barcode", "size"],
    "rule": "",                   # своё правило словами
}


def clean(data):
    """Правила от клиента → проверенные значения (лишнее отбрасывается)."""
    d = dict(DEFAULTS)
    src = data or {}
    if src.get("order") in ORDERS:
        d["order"] = src["order"]
    for k, lo, hi in (("photos_per_product", 0, 50), ("labels_per_product", -1, 5)):
        try:
            d[k] = max(lo, min(hi, int(src.get(k, d[k]))))
        except (TypeError, ValueError):
            pass
    d["article_example"] = re.sub(r"\s+", "", str(src.get("article_example") or ""))[:60]
    for k in ("colors_separate", "sizes_together"):
        if k in src:
            d[k] = bool(src[k])
    if "ignore" in src:
        d["ignore"] = [x for x in (src.get("ignore") or []) if x in IGNORE]
    d["rule"] = str(src.get("rule") or "").strip()[:1000]
    return d


def article_regex(example):
    """Образец артикула → шаблон: буквы → любые буквы, цифры → цифры (длина группы ±1), остальное — как есть.
    «BX096-2» → ^[A-ZА-Я]{1,3}\\d{2,4}-\\d{1,2}$."""
    ex = re.sub(r"\s+", "", str(example or "")).upper()
    if not ex:
        return None
    parts = []
    for m in re.finditer(r"[A-ZА-ЯЁ]+|\d+|.", ex):
        t = m.group(0)
        n = len(t)
        lo, hi = max(1, n - 1), n + 1
        if t[0].isdigit():
            parts.append(rf"\d{{{lo},{hi}}}")
        elif t[0].isalpha():
            parts.append(rf"[A-ZА-ЯЁ]{{{lo},{hi}}}")
        else:
            parts.append(re.escape(t))
    return re.compile("^" + "".join(parts) + "$")


def norm(code):
    return re.sub(r"\s+", "", str(code or "")).upper()


def _not_article(code, ignore):
    """Код, который по правилам продавца артикулом быть не может: размер, штрихкод, цена."""
    c = norm(code)
    if not c:
        return True
    if "size" in ignore and re.fullmatch(r"\d{1,3}([.,]5)?|[XSML]{1,4}|\d{2}[-/]\d{2}", c):
        return True                     # 38, 38.5, XL, 36-37
    if "barcode" in ignore and re.fullmatch(r"\d{8,14}", c):
        return True                     # EAN-8/13, GTIN-14
    if "price" in ignore and re.search(r"(₽|РУБ|RUB|\$|€)", c):
        return True
    return False


def pick_article(article, codes, rx, ignore=()):
    """Артикул из кодов, прочитанных на бирке: по образцу продавца, а без образца — первый код, который не размер,
    не штрихкод и не цена (по списку «игнорировать»)."""
    cands = [c.strip() for c in [article] + [c for c in (codes or []) if isinstance(c, str)] if c and c.strip()]
    if rx is not None:
        for c in cands:
            if rx.match(norm(c)):
                return c
        return "" if len(cands) > 1 or (cands and _not_article(cands[0], ignore)) else article
    for c in cands:
        if not _not_article(c, ignore):
            return c
    return ""


def prompt_section(r):
    """Правила продавца для запроса раскладки (по-английски — так модели точнее)."""
    lines = []
    if r["order"] == "label_after":
        lines.append("The seller photographs each product first and its label/tag LAST — a label closes the product's series.")
    elif r["order"] == "label_before":
        lines.append("The seller photographs the label/tag FIRST and then the product — a label opens a new product's series.")
    elif r["order"] == "no_label":
        lines.append("There are NO label photos: every photo is the product itself (or junk). Group only by appearance.")
    if r["photos_per_product"]:
        lines.append(f"Each product usually has about {r['photos_per_product']} photos; a much longer series of one letter "
                     "most likely contains several products — split it by appearance.")
    if r["labels_per_product"] > 0:
        lines.append(f"Each product usually has {r['labels_per_product']} label photo(s); several labels with the SAME "
                     "article belong to one product.")
    if r["article_example"]:
        lines.append(f"The article code looks like \"{r['article_example']}\" (same pattern of letters, digits and "
                     "separators). Put exactly that code into \"article\"; list every other printed code in \"codes\".")
    lines.append("Different colors of the same model are DIFFERENT products (different letters)." if r["colors_separate"]
                 else "Different colors of the same model are ONE product (same letter).")
    if r["sizes_together"]:
        lines.append("Different sizes of the same model and color are ONE product.")
    ign = {"price": "prices and price tags", "barcode": "barcode digits (EAN)", "size": "size numbers",
           "packaging": "boxes and bags"}
    ig = [ign[x] for x in r["ignore"] if x in ign and x != "packaging"]
    if ig:
        lines.append("Never use " + ", ".join(ig) + " as the article.")
    if "packaging" in r["ignore"]:
        lines.append("Photos of boxes/bags (packaging) are not needed: give them role \"junk\" unless a readable label is "
                     "the main subject.")
    if r["rule"]:
        lines.append("Seller's own words (may be in Russian), follow them: " + r["rule"])
    return "SELLER'S RULES — they override the defaults above:\n- " + "\n- ".join(lines)


def _sig(r, colors):
    kind = norm(r.get("kind"))
    color = norm(r.get("color")) if colors else ""
    return (kind, color) if kind else None


def split_visual(g, colors=True, order="auto"):
    """Группа, в которой подряд идут серии разных по виду товаров (тип или цвет), → части по сериям.

    Серией считаются ≥2 фото товара подряд с одинаковым видом; одиночное «другое» фото (подошва, деталь другого цвета)
    остаётся с соседями. Бирки и упаковка уходят к серии по порядку съёмки: «бирка перед товаром» — к следующей,
    иначе — к предыдущей."""
    prods = [i for i, r in enumerate(g) if r["role"] == "product"]
    sigs = {i: _sig(g[i], colors) for i in prods}
    runs = []                                  # [sig, [индексы фото товара]]
    for i in prods:
        s = sigs[i]
        if runs and (s is None or s == runs[-1][0]):
            runs[-1][1].append(i)
        else:
            runs.append([s, [i]])
    # короткие серии (1 фото) и фото без вида — к соседней серии
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for j, (s, idx) in enumerate(runs):
            if len(idx) < 2 or s is None:
                k = j - 1 if j > 0 else j + 1
                runs[k][1].extend(idx)
                runs[k][1].sort()
                runs.pop(j)
                changed = True
                break
        # соседние серии одного вида — одна серия
        j = 1
        while j < len(runs):
            if runs[j][0] == runs[j - 1][0]:
                runs[j - 1][1] = sorted(runs[j - 1][1] + runs[j][1])
                runs.pop(j)
                changed = True
            else:
                j += 1
    if len(runs) < 2:
        return [g]
    starts = [min(idx) for _, idx in runs]
    owner = {}
    for n, (_, idx) in enumerate(runs):
        for i in idx:
            owner[i] = n
    parts = [[] for _ in runs]
    for i, r in enumerate(g):
        if i in owner:
            n = owner[i]
        elif order == "label_before":           # бирка — к следующей серии
            n = next((k for k, st in enumerate(starts) if st > i), len(runs) - 1)
        else:                                    # бирка — к предыдущей серии
            n = max([k for k, st in enumerate(starts) if st < i] or [0])
        parts[n].append(r)
    return [p for p in parts if p]
