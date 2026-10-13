"""Импорт: клиент загружает кучу фото (файлы, папку, ZIP) → фото в S3 → vision-модель по листам из 20 фото
(с перекрытием 4) определяет роль каждого фото и группы товаров, читает артикул с этикеток →
клиент подтверждает группы → товары и их фото в базе (файлы не копируются: товар ссылается на загруженные)."""
import io
import re
import zipfile
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
from ..db.models import ImportFile, ImportSession, Organization, Product, ProductPhoto, Project
from ..workers.queue import enqueue, set_note
from .common import write_usage

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SORT_CHUNK, SORT_OVERLAP = 20, 4

SORT_PROMPT = """You sort a seller's raw photos of products for a marketplace. Photos are given in shooting order,
each preceded by its id and shooting time. A seller usually photographs one product from several angles, often together
with a photo of its label/tag/box, then moves on to the next product.

For EACH photo decide:
- role: "product" — the product itself (any angle or background, even if a price sticker is visible on it);
  "label" — a close-up of a tag, price tag, box label, sticker, barcode or paper with article/size, where text is the main subject;
  "packaging" — the product's box or bag as the main subject, without a readable label;
  "junk" — blurred, accidental, empty or unrelated photo.
- group: a letter. Photos of the SAME physical product (same model AND color) get the same letter; different products get
  different letters even if they look similar. A label/packaging photo gets the letter of the product it belongs to
  (usually photographed right before or right after it); if that is unclear, use "?".
- product: for product photos, 3–6 English words: type, color, key feature (e.g. "black over-the-knee boots, stiletto").
- article: for label photos, the model/article code exactly as printed (e.g. "BX096-2"); not the barcode digits, not the price. Else "".
- text: for label photos, other useful printed info briefly (brand, size, color, composition). Else "".

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
    if PurePosixPath(parts[-1]).suffix.lower() == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if not info.flag_bits & 0x800:     # имена из русского Windows-архива
                    try:
                        name = name.encode("cp437").decode("cp866")
                    except Exception:
                        pass
                sub = [_safe_name(x) for x in name.replace("\\", "/").split("/") if x not in ("", ".", "..")]
                if not sub or PurePosixPath(sub[-1]).suffix.lower() not in IMG_EXT or "__MACOSX" in sub:
                    continue
                path = "/".join([PurePosixPath(parts[-1]).stem] + sub if len(sub) == 1 else sub)
                files.append((path, z.read(info)))
    elif PurePosixPath(parts[-1]).suffix.lower() in IMG_EXT:
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


def _sort_chunk(st, model, items, trace):
    """items: [(id, bytes, time_str)] → {id: {...}}"""
    content = [{"type": "text", "text": "Photos in shooting order:"}]
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
        if group_mode == "folders":
            rows.sort(key=lambda r: (r["dir"], r["time"], r["name"]))
        else:
            rows.sort(key=lambda r: (r["time"], r["name"]))
        for n, r in enumerate(rows, 1):
            r["id"] = n
        srcs = {k: sum(1 for r in rows if r["src"] == k) for k in ("exif", "name", "upload")}
        log.info("%s анализ: %d фото · время съёмки: EXIF %d, из имени %d, по времени загрузки %d · модель %s · группы: %s",
                 tag, len(rows), srcs["exif"], srcs["name"], srcs["upload"], model,
                 "по папкам архива" if group_mode == "folders" else "автоматически")
        step = SORT_CHUNK - SORT_OVERLAP
        starts = list(range(0, max(len(rows) - SORT_OVERLAP, 1), step)) or [0]
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
            got, cost, secs = _sort_chunk(st, model, items, trace)
            total_cost += cost
            answers.append((c, got))
            _update(session_id, progress=[c + 1, len(starts)], cost_rub=total_cost)
            log.info("%s лист %d/%d (фото %d–%d) за %.1f с, %.2f ₽", tag, c + 1, len(starts),
                     part[0]["id"], part[-1]["id"], secs, cost)
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

        def union(a, b):
            parent[find(a)] = find(b)

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
        for pid, ks in keys.items():
            for k in ks[1:]:
                union(ks[0], k)

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
                a = re.sub(r"\s+", "", r["article"]).upper()
                if r["role"] == "label" and a and r["gkey"]:
                    if a in art_key and find(art_key[a]) != find(r["gkey"]):
                        log.info("%s группы объединены по одинаковому артикулу %s", tag, r["article"])
                        union(r["gkey"], art_key[a])
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
        out, noname, used = [], 0, set()
        for k in order:
            if k == "_junk":
                continue
            g = groups[k]
            arts = [r["article"] for r in g if r["role"] == "label" and r["article"]]
            texts = [r["text"] for r in g if r["role"] == "label" and r["text"]]
            prods = [r["product"] for r in g if r["role"] == "product" and r["product"]]
            if isinstance(k, tuple) and k[0] == "dir":
                name = k[1]
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


def _update(session_id, **kw):
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        for k, v in kw.items():
            setattr(sess, k, v)


def start_analysis(session_id, group_mode, label_mode):
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        sess.options = {"group_mode": group_mode, "label_mode": label_mode}
        sess.status, sess.error, sess.cost_rub, sess.progress = "analyzing", "", 0.0, [0, 0]
        enqueue(s, "import", sess.project_id, payload={"session": session_id}, priority=10)


def apply(session_id, groups, label_mode, auto_profile):
    """groups: [{name, photos: [[rel_path, role]]}] — то, что клиент подтвердил на экране."""
    tag = f"[импорт {session_id}]"
    with db.session() as s:
        sess = s.get(ImportSession, session_id)
        files = {f.rel_path: f for f in s.scalars(select(ImportFile).where(ImportFile.session_id == session_id)).all()}
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
            if labs and label_mode != "skip":
                arts = set((p.label_data or {}).get("articles") or [])
                texts = list((p.label_data or {}).get("texts") or [])
                for n in labs:
                    if files[n].asset_id not in have:
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


def analyze_request(session_id, group_mode, label_mode):
    with db.session() as s:
        sess = s.get(ImportSession, int(session_id))
        if not sess:
            raise LookupError("сессия импорта не найдена")
        if sess.status == "analyzing":
            raise ValueError("анализ уже идёт")
        if not s.scalar(select(func.count(ImportFile.id)).where(ImportFile.session_id == sess.id)):
            raise ValueError("сначала загрузите фото")
    start_analysis(session_id, group_mode, label_mode)


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
