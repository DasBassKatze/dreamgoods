"""Импорт: клиент загружает кучу фото (файлы или папку; архивы не принимаются) → фото в S3 → vision-модель по листам из 20 фото
(с перекрытием 4) определяет роль каждого фото и группы товаров, читает артикул с этикеток →
клиент подтверждает группы → товары и их фото в базе (файлы не копируются: товар ссылается на загруженные)."""
import re
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import func, select

from .. import db
from ..ai.images import jpeg_data_url
from ..ai.polza import chat
from ..core import storage
from ..core.events import say
from ..core.logs import Trace, log
from ..core.settings import effective
from ..db.models import (Asset, Generation, ImportFile, ImportSession, Organization, PersonaPhoto, Product, ProductPhoto,
                         Project, StyleRefPhoto)
from ..workers.queue import enqueue, set_note
from .common import write_usage

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SORT_CHUNK, SORT_OVERLAP = 20, 4

SORT_PROMPT = """You sort a seller's raw photos of products for a marketplace. Photos are given in shooting order,
each preceded by its id and shooting time. A seller usually photographs one product from several angles, often together
with a photo of its label/tag/box, then moves on to the next product.

For EACH photo decide:
- role: "product" — the product itself (any angle or background), INCLUDING photos where a tag, sticker or label is
  attached to the product but the product (or its part: sole, inside, lining, heel) is still clearly visible — e.g. a
  sole with a size sticker. Such photos are used for generation; still read the article/text from that label;
  "label" — a close-up of a tag, price tag, box label, sticker, barcode or paper with article/size, where text is the main subject;
  "packaging" — the product's box or bag as the main subject, without a readable label;
  "junk" — blurred, accidental, empty or unrelated photo.
- group: a letter. Photos of the SAME physical product (same model AND color) get the same letter; different products get
  different letters even if they look similar. A label/packaging photo gets the letter of the product it belongs to
  (usually photographed right before or right after it); if that is unclear, use "?".
- product: for product photos, 3–6 English words: type, color, key feature (e.g. "black over-the-knee boots, stiletto").
- article: for label photos AND product photos with a readable label on them — the model/article code exactly as printed
  (e.g. "BX096-2"); not the barcode digits, not the price. Else "". Different article codes mean different products:
  never give the same group letter to photos whose labels show different articles.
- text: for the same photos, other useful printed info briefly (brand, size, color, composition). Else "".

Reply with ONLY one JSON object, no markdown:
{"photos":[{"id":1,"role":"product","group":"A","product":"...","article":"","text":""}]}"""


def _safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return name[:80] or "без_названия"


def _shot_time(asset, rel):
    """Время съёмки: EXIF (сохранено в asset.shot_at) → имя файла вида 20261003_163252 → время загрузки."""
    if asset.shot_at:
        return asset.shot_at.replace(tzinfo=None).timestamp(), "exif"
    m = re.search(r"(20\d{6})[_\-\s]?(\d{6})", PurePosixPath(rel).name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp(), "name"
        except ValueError:
            pass
    return asset.created_at.timestamp(), "upload"


def save_upload(session_id, rel, data):
    """Файл или ZIP из браузера → S3 + import_files. Возвращает число добавленных фото."""
    rel = rel.replace("\\", "/").lstrip("/")
    parts = [_safe_name(x) for x in rel.split("/") if x not in ("", ".", "..")]
    if not parts:
        raise ValueError("пустое имя файла")
    files = []
    if PurePosixPath(parts[-1]).suffix.lower() in (".zip", ".rar", ".7z"):
        # архивы не принимаем: содержимое не видно до распаковки и его нельзя проверить — нужна папка или фото
        raise ValueError("архивы не поддерживаются — распакуйте архив и загрузите папку или фото")
    if PurePosixPath(parts[-1]).suffix.lower() in IMG_EXT:
        files.append(("/".join(parts), data))
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        org_id = s.get(Project, sess.project_id).client.org_id
        n = 0
        for path, content in files:
            if s.scalar(select(ImportFile.id).where(ImportFile.session_id == session_id, ImportFile.rel_path == path)):
                continue
            a = storage.put(s, org_id, content, "import", PurePosixPath(path).name)
            s.add(ImportFile(session_id=session_id, asset_id=a.id, rel_path=path))
            n += 1
        if sess.status not in ("upload",):
            sess.status = "upload"
        total = s.scalar(select(func.count(ImportFile.id)).where(ImportFile.session_id == session_id))
    return n, total


def _art(a):
    """Артикул для сравнения: без пробелов, в верхнем регистре."""
    return re.sub(r"\s+", "", str(a or "")).upper()


def _split_by_articles(g):
    """Группа с бирками разных артикулов → части по одному артикулу.

    Фото идут в порядке съёмки. Если группа начинается с бирки — бирку снимали перед товаром, и каждая бирка
    открывает новую часть; иначе бирку снимали после товара, и бирка закрывает часть."""
    arts = [_art(r["article"]) for r in g]
    if len({a for a in arts if a}) < 2:
        return [g]
    first_label = next((i for i, a in enumerate(arts) if a), 0)
    before = all(not a or g[i]["role"] == "label" for i, a in enumerate(arts[:first_label + 1])) and \
        not any(g[i]["role"] == "product" for i in range(first_label))
    parts, cur, cur_art = [], [], ""
    for r, a in zip(g, arts):
        if before:
            if a and cur and cur_art and a != cur_art:
                parts.append(cur)
                cur = []
            cur.append(r)
            cur_art = a or cur_art
        else:
            if a and cur_art and a != cur_art:
                parts.append(cur)
                cur = []
            cur.append(r)
            cur_art = a or cur_art
            if a and r["role"] == "label":
                parts.append(cur)
                cur, cur_art = [], ""
    if cur:
        if parts and not any(x["role"] == "product" for x in cur):
            parts[-1].extend(cur)           # хвост из одних бирок/упаковки — к последнему товару
        else:
            parts.append(cur)
    # части без фото товара (одни бирки) — к соседней части
    out = []
    for part in parts:
        if out and not any(x["role"] == "product" for x in part):
            out[-1].extend(part)
        else:
            out.append(part)
    if len(out) > 1 and not any(x["role"] == "product" for x in out[0]):
        out[1] = out[0] + out[1]
        out.pop(0)
    return out


def _sort_chunk(st, model, items, trace, rule=""):
    """items: [(id, bytes, time_str)] → {id: {...}}; rule — правило раскладки от продавца (его словами)."""
    content = []
    if rule:
        content.append({"type": "text", "text": "The seller's own sorting rule (may be in Russian). Follow it — it overrides "
                        "the default assumptions about how products were photographed, but keep the reply format:\n" + rule})
    content.append({"type": "text", "text": "Photos in shooting order:"})
    for pid, data, ts in items:
        content.append({"type": "text", "text": f"Photo {pid} (shot at {ts}):"})
        content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(data, 512)}})
    res, cost, secs = chat(st, model, SORT_PROMPT, content, trace, "сортировка", 4000, "none")
    out = {}
    for ph in res.get("photos") or []:
        try:
            pid = int(ph.get("id")) if isinstance(ph, dict) else None
        except (TypeError, ValueError):
            pid = None
        if pid is not None:
            out[pid] = ph
    return out, cost, secs


def analyze(session_id, job_id=None):
    trace = Trace(f"[импорт {session_id}]")
    tag = str(trace)
    try:
        with db.session() as s:
            sess = s.get(ImportSession, session_id)
            project = s.get(Project, sess.project_id)
            org = s.get(Organization, project.client.org_id)
            st = effective(org, project)
            group_mode = sess.options.get("group_mode", "auto")
            label_mode = sess.options.get("label_mode", "read")
            rule = str(sess.options.get("sort_rule") or "").strip()[:1000]
            files = s.scalars(select(ImportFile).where(ImportFile.session_id == session_id)).all()
            rows = []
            for f in files:
                t, src = _shot_time(f.asset, f.rel_path)
                parts = PurePosixPath(f.rel_path).parts
                rows.append({"name": f.rel_path, "asset": str(f.asset_id), "key": f.asset.storage_key, "time": t, "src": src,
                             "dir": parts[0] if len(parts) > 1 else "", "fid": f.id})
            existing = {p.lower() for p in s.scalars(select(Product.sku).where(Product.project_id == project.id)).all()}
            ids = dict(org=org.id, project=project.id)
        if not rows:
            raise RuntimeError("нет загруженных фото")
        model = (st.get("profile_model") or "").strip() or st.get("qc_model")
        no_ai = group_mode == "none"          # «просто загрузить»: без ИИ — по папкам, все фото — фото товара
        if no_ai:
            group_mode = "folders"
        if group_mode == "folders":
            rows.sort(key=lambda r: (r["dir"], r["time"], r["name"]))
        else:
            rows.sort(key=lambda r: (r["time"], r["name"]))
        for n, r in enumerate(rows, 1):
            r["id"] = n
        srcs = {k: sum(1 for r in rows if r["src"] == k) for k in ("exif", "name", "upload")}
        log.info("%s анализ: %d фото · время съёмки: EXIF %d, из имени %d, по времени загрузки %d · модель %s · группы: %s",
                 tag, len(rows), srcs["exif"], srcs["name"], srcs["upload"], model,
                 "по папкам" if group_mode == "folders" else "автоматически" + (" + правило продавца" if rule else ""))
        step = SORT_CHUNK - SORT_OVERLAP
        starts = [] if no_ai else (list(range(0, max(len(rows) - SORT_OVERLAP, 1), step)) or [0])
        _update(session_id, status="analyzing", progress=[0, len(starts)])
        answers, total_cost = [], 0.0
        for c, a in enumerate(starts):
            part = rows[a:a + SORT_CHUNK]
            prev, items = None, []
            for r in part:
                dt = datetime.fromtimestamp(r["time"])
                gap = f", +{int(r['time'] - prev)} s after previous" if prev is not None else ""
                items.append((r["id"], storage.get(r["key"]), dt.strftime("%H:%M:%S") + gap))
                prev = r["time"]
            if job_id:
                set_note(job_id, f"лист {c + 1}/{len(starts)}")
            got, cost, secs = _sort_chunk(st, model, items, trace, rule if group_mode == "auto" else "")
            total_cost += cost
            answers.append((c, got))
            _update(session_id, progress=[c + 1, len(starts)], cost_rub=total_cost)
            log.info("%s лист %d/%d (фото %d–%d) за %.1f с, %.2f ₽", tag, c + 1, len(starts),
                     part[0]["id"], part[-1]["id"], secs, cost)
        if starts:
            with db.session() as s:
                write_usage(s, ids["org"], ids["project"], None, None, trace, f"import:{session_id}")
        # объединение групп между листами через перекрывающиеся фото (union-find)
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        arts_of = {}            # корень группы → артикулы с её бирок (разные артикулы — разные товары)

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra == rb:
                return True
            A, B = arts_of.get(ra, set()), arts_of.get(rb, set())
            if A and B and not (A & B):
                return False         # у обеих групп свои, разные артикулы — не склеиваем
            parent[ra] = rb
            arts_of[rb] = A | B
            arts_of.pop(ra, None)
            return True

        info = {r["id"]: {} for r in rows}
        keys = {r["id"]: [] for r in rows}
        for c, got in answers:
            for pid, ph in got.items():
                if pid not in info:
                    continue
                # последний лист, видевший фото, уточняет данные
                info[pid] = {**info[pid], **{k: v for k, v in ph.items() if v not in (None, "")}}
                g = str(ph.get("group") or "?").strip()
                if g and g != "?" and str(ph.get("role")) != "junk":
                    keys[pid].append((c, g))
        for pid, ph in info.items():
            a = _art(ph.get("article"))
            if a and str(ph.get("role")) != "junk":
                for k in keys[pid]:
                    arts_of.setdefault(find(k), set()).add(a)
        for pid, ks in keys.items():
            for k in ks[1:]:
                if not union(ks[0], k):
                    log.info("%s листы: группы с разными артикулами не склеены (%s)", tag,
                             ", ".join(sorted(arts_of.get(find(ks[0]), set()) | arts_of.get(find(k), set()))))

        for r in rows:
            ph = info.get(r["id"]) or {}
            role = str(ph.get("role") or "product").lower()
            r["role"] = role if role in ("product", "label", "packaging", "junk") else "product"
            r["product"] = str(ph.get("product") or "")
            r["article"] = str(ph.get("article") or "").strip()
            r["text"] = str(ph.get("text") or "").strip()
            r["gkey"] = find(keys[r["id"]][0]) if keys[r["id"]] else None

        if group_mode == "folders":
            for r in rows:
                r["gkey"] = ("dir", r["dir"] or "без_папки") if r["role"] != "junk" else None
        else:
            # этикетки без группы или с «пустой» группой — к ближайшему по времени фото товара
            prod_keys = {r["gkey"] for r in rows if r["role"] == "product" and r["gkey"]}
            for r in rows:
                if r["role"] in ("label", "packaging") and r["gkey"] not in prod_keys:
                    best, bd = None, None
                    for q in rows:
                        if q["role"] == "product" and q["gkey"]:
                            d = abs(q["time"] - r["time"]) + (0.5 if q["id"] < r["id"] else 0)
                            if bd is None or d < bd:
                                best, bd = q["gkey"], d
                    r["gkey"] = best
            # одинаковый артикул на этикетках разных групп — это один товар
            art_key = {}
            for r in rows:
                a = _art(r["article"])
                if r["role"] in ("label", "product") and a and r["gkey"]:
                    if a in art_key and find(art_key[a]) != find(r["gkey"]):
                        if union(r["gkey"], art_key[a]):
                            log.info("%s группы объединены по одинаковому артикулу %s", tag, r["article"])
                    art_key.setdefault(a, r["gkey"])
            for r in rows:
                if r["gkey"] and not (isinstance(r["gkey"], tuple) and r["gkey"][0] == "dir"):
                    r["gkey"] = find(r["gkey"])

        # мусор и фото без группы — в отдельную исключённую группу
        groups, order = {}, []
        for r in rows:
            k = r["gkey"] if r["role"] != "junk" else "_junk"
            k = k or "_junk"
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(r)
        # в одной группе оказались бирки с разными артикулами — делим её по биркам (раздельных товаров несколько)
        split_order = []
        for k in order:
            parts = [groups[k]] if k == "_junk" or group_mode == "folders" else _split_by_articles(groups[k])
            if len(parts) > 1:
                log.info("%s группа разделена по артикулам: %s", tag,
                         ", ".join(sorted({_art(r["article"]) for r in groups[k] if _art(r["article"])})))
            for i, part in enumerate(parts):
                nk = k if i == 0 else (k, "part", i)
                groups[nk] = part
                split_order.append(nk)
        order = split_order
        out, noname, used = [], 0, set()
        for k in order:
            if k == "_junk":
                continue
            g = groups[k]
            arts = [r["article"] for r in g if r["role"] in ("label", "product") and r["article"]]
            texts = [r["text"] for r in g if r["role"] in ("label", "product") and r["text"]]
            prods = [r["product"] for r in g if r["role"] == "product" and r["product"]]
            if isinstance(k, tuple) and k[0] == "dir" and len(k) == 2:
                name = k[1] if k[1] != "без_папки" else "товар_01"
            elif arts:
                name = max(set(arts), key=arts.count)
            else:
                noname += 1
                name = f"без_артикула_{noname:02d}"
            name = _safe_name(name)
            base, n = name, 2
            while name.lower() in used:
                name, n = f"{base}_{n}", n + 1
            used.add(name.lower())
            out.append({"id": f"g{len(out) + 1}", "name": name, "article": arts[0] if arts else "",
                        "articles": sorted(set(arts)), "text": "; ".join(dict.fromkeys(texts)),
                        "product": max(set(prods), key=prods.count) if prods else "",
                        "photos": [r["name"] for r in g], "exists": name.lower() in existing})
        if "_junk" in groups:
            out.append({"id": "junk", "name": "Не использовать", "article": "", "articles": [], "text": "",
                        "product": "", "photos": [r["name"] for r in groups["_junk"]], "exists": False, "junk": True})
        photos = [{k: r[k] for k in ("id", "name", "asset", "time", "src", "role", "product", "article", "text", "dir")}
                  for r in rows]
        if label_mode == "keep":
            for ph in photos:
                if ph["role"] == "label":
                    ph["role"] = "product"
        with db.session() as s:
            by_fid = {r["fid"]: r for r in rows}
            for f in s.scalars(select(ImportFile).where(ImportFile.session_id == session_id)).all():
                r = by_fid.get(f.id)
                if r:
                    f.analysis = {k: r.get(k) for k in ("id", "role", "product", "article", "text", "src")}
            sess = s.get(ImportSession, session_id)
            sess.groups, sess.status, sess.result = out, "ready", {"photos": photos}
        n_lab = sum(1 for r in rows if r["role"] == "label")
        say("ok", f"📥 Импорт: {len(rows)} фото → групп {len([g for g in out if not g.get('junk')])}, этикеток {n_lab}, "
                  f"не использовать {len(groups.get('_junk', []))} · {total_cost:.2f} ₽. Проверьте группы и подтвердите",
            ids["project"])
    except Exception as e:
        _update(session_id, status="error", error=str(e)[:400])
        raise


def _feedback(sess, files, groups, tag):
    """Сравнение раскладки ИИ с тем, что подтвердил пользователь: у каждого фото — группа и роль от ИИ и итоговые,
    у сессии — сводка и отмеченные «ошибки раскладки». Нужно для разбора качества раскладки (выгрузка проверки)."""
    ai_group = {}
    for g in sess.groups or []:
        for n in g.get("photos") or []:
            ai_group[n] = "_junk" if g.get("junk") else g.get("id")
    ai_role = {ph["name"]: ph.get("role") for ph in (sess.result or {}).get("photos") or []}
    final = {}
    for i, g in enumerate(groups):
        for n, r in g.get("photos") or []:
            final[n] = (i, r)
    # группа ИИ → в какую итоговую группу ушло больше всего её фото; фото, ушедшие в другую, — перенесённые
    major = {}
    for n, (i, r) in final.items():
        major.setdefault(ai_group.get(n), {}).setdefault(i, 0)
        major[ai_group.get(n)][i] += 1
    main_of = {k: max(v, key=v.get) for k, v in major.items()}
    owner = {}
    for k, i in main_of.items():
        owner.setdefault(i, k)
    moved = role_changed = 0
    for n, f in files.items():
        i, r = final.get(n, (None, "junk"))
        g_ai = ai_group.get(n)
        was_moved = i is not None and g_ai is not None and g_ai != "_junk" and owner.get(i) != g_ai
        changed = bool(ai_role.get(n)) and ai_role.get(n) != r
        moved += was_moved
        role_changed += changed
        f.analysis = {**(f.analysis or {}), "ai_group": g_ai, "final_group": groups[i].get("name") if i is not None else "",
                      "final_role": r, "moved": was_moved, "role_changed": changed}
    flagged = [{"name": g.get("name"), "photos": len(g.get("photos") or [])} for g in groups if g.get("sort_error")]
    sess.result = {**(sess.result or {}), "feedback": {"moved": moved, "role_changed": role_changed, "flagged": flagged,
                                                        "ai_groups": len([g for g in sess.groups or [] if not g.get("junk")]),
                                                        "final_groups": len(groups)}}
    if moved or role_changed or flagged:
        log.info("%s правки раскладки: перенесено фото %d, сменена роль %d, групп ИИ %d → итог %d%s", tag, moved,
                 role_changed, sess.result["feedback"]["ai_groups"], len(groups),
                 f"; отмечены ошибки: {', '.join(x['name'] for x in flagged)}" if flagged else "")


def _update(session_id, **kw):
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        for k, v in kw.items():
            setattr(sess, k, v)


def start_analysis(session_id, group_mode, label_mode, sort_rule=""):
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        sess.options = {"group_mode": group_mode, "label_mode": label_mode, "sort_rule": (sort_rule or "").strip()[:1000]}
        sess.status, sess.error, sess.cost_rub, sess.progress = "analyzing", "", 0.0, [0, 0]
        enqueue(s, "import", sess.project_id, payload={"session": session_id}, priority=10)


def apply(session_id, groups, label_mode, auto_profile):
    """groups: [{name, photos: [[rel_path, role]]}] — то, что клиент подтвердил на экране."""
    tag = f"[импорт {session_id}]"
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        files = {f.rel_path: f for f in s.scalars(select(ImportFile).where(ImportFile.session_id == session_id)).all()}
        _feedback(sess, files, groups, tag)
        made, added, labels, merged, new_ids = [], 0, 0, [], []
        for g in groups:
            items = [(n, r) for n, r in (g.get("photos") or []) if n in files and r != "junk"]
            prods = [n for n, r in items if r in ("product", "packaging")]
            labs = [n for n, r in items if r == "label"]
            if not prods:
                if labs:
                    log.warning("%s группа «%s»: только этикетки, без фото товара — пропущена", tag, g.get("name"))
                continue
            sku = _safe_name(g.get("name") or "без_названия")
            p = s.scalar(select(Product).where(Product.project_id == sess.project_id, func.lower(Product.sku) == sku.lower()))
            if p:
                merged.append(sku)
            else:
                p = Product(project_id=sess.project_id, sku=sku)
                s.add(p)
                s.flush()
                new_ids.append(p.id)
            pos = (s.scalar(select(func.max(ProductPhoto.position)).where(ProductPhoto.product_id == p.id)) or 0)
            have = set(s.scalars(select(ProductPhoto.asset_id).where(ProductPhoto.product_id == p.id)).all())
            for n in prods:
                if files[n].asset_id in have:
                    continue
                pos += 1
                s.add(ProductPhoto(product_id=p.id, asset_id=files[n].asset_id, role=dict(items)[n], is_reference=True,
                                   position=pos))
                added += 1
            tagged = [n for n in prods if (files[n].analysis or {}).get("article") or (files[n].analysis or {}).get("text")]
            if (labs or tagged) and label_mode != "skip":
                arts = set((p.label_data or {}).get("articles") or [])
                texts = list((p.label_data or {}).get("texts") or [])
                for n in labs + tagged:          # бирки и фото товара с биркой на нём (подошва с наклейкой)
                    if n in labs and files[n].asset_id not in have:
                        pos += 1
                        s.add(ProductPhoto(product_id=p.id, asset_id=files[n].asset_id, role="label", is_reference=False,
                                           position=pos))
                        labels += 1
                    an = files[n].analysis or {}
                    if an.get("article"):
                        arts.add(an["article"])
                    if an.get("text") and an["text"] not in texts:
                        texts.append(an["text"])
                p.label_data = {"articles": sorted(arts), "texts": texts}
            desc = str(g.get("description") or "").strip()[:2000]
            if desc:                     # описание товара словами — в профиль (подсказка ИИ вместе с текстом бирки)
                p.label_data = {**(p.label_data or {}), "user_text": desc}
            made.append(sku)
            log.info("%s → товар %s: фото товара %d, этикеток %d%s", tag, sku, len(prods), len(labs) if label_mode != "skip" else 0,
                     " (товар уже был — фото добавлены)" if sku in merged else "")
        res = {"folders": made, "photos": added, "labels": labels, "merged": merged}
        sess.status, sess.result = "done", {**(sess.result or {}), **res}
        project_id = sess.project_id
        if auto_profile:
            for pid in new_ids:
                enqueue(s, "profile", project_id, product_id=pid, payload={"build": True}, priority=20)
    say("ok", f"📥 Разложено: {added} фото в {len(made)} товаров, этикеток {labels}"
        + (f"; дополнены существующие: {', '.join(merged)}" if merged else ""), project_id)
    if auto_profile and new_ids:
        say("info", f"🧠 Составляю профили и промпты для новых товаров: {len(new_ids)}", project_id)
    return res


# ───────── сессия импорта для API ─────────

def new_session(project_id):
    with db.session() as s:
        sess = ImportSession(project_id=project_id)
        s.add(sess)
        s.flush()
        return sess.id


def get_session(session_id, project_id=None):
    """Проверяет, что сессия существует (и принадлежит проекту, если он указан). Возвращает (статус, проект)."""
    with db.session() as s:
        sess = s.get(ImportSession, int(session_id))
        if not sess or (project_id is not None and sess.project_id != project_id):
            raise LookupError("сессия импорта не найдена")
        return sess.status, sess.project_id


def view(session_id):
    with db.session() as s:
        sess = s.get(ImportSession, int(session_id))
        if not sess:
            raise LookupError("сессия импорта не найдена")
        count = s.scalar(select(func.count(ImportFile.id)).where(ImportFile.session_id == sess.id))
        return {"id": sess.id, "project_id": sess.project_id, "status": sess.status, "progress": sess.progress,
                "error": sess.error, "photos": (sess.result or {}).get("photos", []), "groups": sess.groups or [],
                "cost": round(sess.cost_rub or 0, 2), "count": count,
                "result": {k: v for k, v in (sess.result or {}).items() if k != "photos"}}


def upload(session_id, path, data):
    status, _ = get_session(session_id)
    if status in ("analyzing", "applying"):
        raise ValueError("сессия импорта сейчас занята")
    return save_upload(session_id, path, data)


def analyze_request(session_id, group_mode, label_mode, sort_rule=""):
    with db.session() as s:
        sess = s.get(ImportSession, int(session_id))
        if not sess:
            raise LookupError("сессия импорта не найдена")
        if sess.status == "analyzing":
            raise ValueError("анализ уже идёт")
        if not s.scalar(select(func.count(ImportFile.id)).where(ImportFile.session_id == sess.id)):
            raise ValueError("сначала загрузите фото")
    start_analysis(session_id, group_mode, label_mode, sort_rule)


def cancel(session_id):
    """Отказ от незавершённой загрузки: загруженные фото удаляются из базы и хранилища, чтобы не занимать место.
    Файл остаётся, если он нужен где-то ещё (то же фото уже есть у товара, в другой загрузке, у модели или оформления)."""
    with db.session() as s:
        sess = s.get(ImportSession, int(session_id))
        if not sess:
            raise LookupError("сессия импорта не найдена")
        if sess.status in ("analyzing", "applying"):
            raise ValueError("сессия импорта сейчас занята — дождитесь окончания анализа")
        if sess.status == "done":
            return {"deleted": 0, "freed": 0}
        files = s.scalars(select(ImportFile).where(ImportFile.session_id == sess.id)).all()
        asset_ids = {f.asset_id for f in files}
        for f in files:
            s.delete(f)
        sess.status, sess.groups, sess.result = "cancelled", [], {}
        s.flush()
        keys, freed, deleted = set(), 0, 0
        for a in s.scalars(select(Asset).where(Asset.id.in_(asset_ids or {None}))).all():
            if _asset_used(s, a.id):
                continue
            keys.add(a.storage_key)
            freed += a.bytes or 0
            deleted += 1
            s.delete(a)
        s.flush()
        # одинаковые файлы хранятся один раз — удаляем файл, только если на него не ссылается ни одна запись
        still = set(s.scalars(select(Asset.storage_key).where(Asset.storage_key.in_(keys or {""}))).all())
        project_id = sess.project_id
    removed = 0
    for k in keys - still:
        try:
            storage.remove(k)
            removed += 1
        except Exception as e:          # файл не удалился — место освободится при следующей уборке, загрузка всё равно отменена
            log.warning("[импорт %s] файл %s не удалён: %s", session_id, k, e)
    log.info("[импорт %s] загрузка отменена: удалено фото %d (файлов %d, %.1f МБ)", session_id, deleted, removed, freed / 1e6)
    say("info", f"🗑 Загрузка отменена: удалено фото {deleted}", project_id)
    from .projects import _storage_cache
    _storage_cache.clear()
    return {"deleted": deleted, "freed": freed}


def _asset_used(s, asset_id):
    """На файл ссылается что-то кроме отменённой загрузки."""
    for col in (ProductPhoto.asset_id, PersonaPhoto.asset_id, StyleRefPhoto.asset_id, Generation.output_asset_id,
                ImportFile.asset_id):
        if s.scalar(select(func.count()).select_from(col.class_).where(col == asset_id)):
            return True
    return False


def apply_request(session_id, groups, label_mode, auto_profile):
    with db.session() as s:
        sess = s.get(ImportSession, int(session_id))
        if not sess or sess.status != "ready":
            raise ValueError("нечего раскладывать: сначала анализ")
        sess.status = "applying"
    try:
        return apply(session_id, groups, label_mode, auto_profile)
    except Exception:
        _update(session_id, status="ready")
        raise
