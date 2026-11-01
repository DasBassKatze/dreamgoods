"""Выгрузка данных ИИ-проверки для разбора (мастер): ZIP с CSV и, по желанию, картинками спорных кадров.

Ключей, паролей и балансов в выгрузке нет — только кадры, промпты, профили товаров, результаты проверок
и ручные решения. Состав архива описан в README.txt внутри.
"""
import csv
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageOps
from sqlalchemy import select

from .. import db
from ..core import storage
from ..core.logs import log
from ..db.models import (Asset, Client, Frame, Generation, ImportFile, ImportSession, Product, ProductPhoto,
                         ProductProfile, Project, QCCheck, Review, SpecCache)

MAX_IMAGES = 400          # кадров с картинками в одном архиве
IMG_SIDE = 1024           # сторона картинки в архиве: хватает для разбора, архив остаётся небольшим

README = """Выгрузка данных ИИ-проверки DreamGoods
=====================================
checks.csv    — каждая проверка каждой попытки генерации: товар, кадр, попытка, модель генерации, итог попытки,
                прошла ли проверка, причины брака, технические замечания, подсчёт людей/товара, промпт кадра
                и ручное решение человека по этой попытке (если было).
reviews.csv   — ручные решения: verdict (ok/bad) против ai_verdict (pass/fail), тип расхождения
                (false_alarm — ИИ зря забраковал, missed — ИИ пропустил брак), комментарий.
profiles.csv  — текущие профили товаров (описание, застёжки и их стороны, детали, чек-лист) — JSON.
references.csv— фото товаров: ракурс и что на них видно.
expectations.csv — ожидания по тексту задания (сколько людей/товара, что запрещено) — кэш проверки.
import_sort.csv — раскладка фото при загрузке: роль и группа от ИИ против итога пользователя (перенесено ли фото,
                сменена ли роль), отметка «ошибка раскладки» у товара, артикул и текст, прочитанные ИИ.
images/       — картинки попыток (gen_<id>.jpg) и фото товаров (ref_<sku>_<n>.jpg), если выбрано «с картинками».
"""


def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    return ("﻿" + buf.getvalue()).encode("utf-8")     # BOM — Excel откроет кириллицу без танцев


def _jpeg(data):
    from ..ai.images import DECODE_SLOTS, open_small
    with DECODE_SLOTS, open_small(data, IMG_SIDE) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((IMG_SIDE, IMG_SIDE), Image.BILINEAR)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=85)
        return out.getvalue()


def _j(v):
    return json.dumps(v, ensure_ascii=False) if v not in (None, "", [], {}) else ""


def build(org_id, project_id=None, days=None, images="disputed"):
    """images: none — без картинок; disputed — попытки с браком или с расхождением человека и ИИ; all — все проверенные."""
    since = datetime.now(timezone.utc) - timedelta(days=int(days)) if days else None
    with db.session() as s:
        q = (select(QCCheck, Generation, Frame, Product, Project, Client)
             .join(Frame, Frame.id == QCCheck.frame_id)
             .join(Product, Product.id == Frame.product_id)
             .join(Project, Project.id == Product.project_id)
             .join(Client, Client.id == Project.client_id)
             .outerjoin(Generation, Generation.id == QCCheck.generation_id)
             .where(Client.org_id == org_id))
        if project_id:
            q = q.where(Project.id == project_id)
        if since:
            q = q.where(QCCheck.created_at >= since)
        rows = s.execute(q.order_by(QCCheck.id)).all()

        frame_ids = {f.id for _, _, f, _, _, _ in rows}
        reviews = s.scalars(select(Review).where(Review.frame_id.in_(frame_ids or {0})).order_by(Review.id)).all()
        by_gen = {r.generation_id: r for r in reviews if r.generation_id}       # последнее решение по попытке
        by_frame = {r.frame_id: r for r in reviews}

        checks, want_gens = [], {}
        for c, g, f, p, pr, cl in rows:
            rv = by_gen.get(c.generation_id) or (by_frame.get(f.id) if g is None else None)
            disputed = (not c.passed) or (rv is not None and rv.verdict != ("ok" if c.passed else "bad"))
            img = ""
            if g is not None and g.output_asset_id and (images == "all" or (images == "disputed" and disputed)):
                img = f"images/gen_{g.id}.jpg"
                want_gens[g.id] = g.output_asset_id
            checks.append({
                "check_id": c.id, "created": c.created_at.isoformat(timespec="seconds") if c.created_at else "",
                "client": cl.name, "project": pr.name, "sku": p.sku, "product": p.name, "category": p.category,
                "frame_id": f.id, "frame_no": f.position, "block": f.block, "generation_id": c.generation_id,
                "attempt": g.attempt if g else "", "gen_model": g.model if g else "", "gen_outcome": g.outcome if g else "",
                "qc_model": c.model, "passed": "да" if c.passed else "нет", "reasons": " | ".join(map(str, c.reasons or [])),
                "tech": " | ".join(map(str, c.tech or [])), "counts": _j(c.counts), "info": _j(c.info),
                "qc_cost_rub": round(c.cost_rub or 0, 3), "source": c.source,
                "human_verdict": rv.verdict if rv else "", "human_note": rv.note_kind if rv else "",
                "human_comment": rv.comment if rv else "", "disputed": "да" if disputed else "",
                "prompt": (g.prompt if g and g.prompt else f.prompt) or "", "image": img})

        rev_rows = [{"review_id": r.id, "created": r.created_at.isoformat(timespec="seconds") if r.created_at else "",
                     "frame_id": r.frame_id, "generation_id": r.generation_id, "verdict": r.verdict,
                     "ai_verdict": r.ai_verdict, "note_kind": r.note_kind, "comment": r.comment} for r in reviews]

        prod_ids = {p.id for _, _, _, p, _, _ in rows}
        profiles = []
        for p in s.scalars(select(Product).where(Product.id.in_(prod_ids or {0}))).all():
            prof = s.get(ProductProfile, p.current_profile_id) if p.current_profile_id else None
            profiles.append({"sku": p.sku, "product": p.name, "category": p.category,
                             "profile_version": prof.version if prof else "", "profile": _j(prof.data) if prof else ""})
        refs, want_refs = [], []
        for ph, p in s.execute(select(ProductPhoto, Product).join(Product, Product.id == ProductPhoto.product_id)
                               .where(Product.id.in_(prod_ids or {0}), ProductPhoto.role != "label")
                               .order_by(Product.sku, ProductPhoto.position, ProductPhoto.id)).all():
            name = f"images/ref_{p.sku}_{len([r for r in refs if r['sku'] == p.sku]) + 1}.jpg"
            safe = "".join(ch if ch.isalnum() or ch in "._-/" else "_" for ch in name)
            refs.append({"sku": p.sku, "view": ph.view, "visible": ph.view_note, "reference": "да" if ph.is_reference else "",
                         "image": safe if images != "none" else ""})
            if images != "none":
                want_refs.append((safe, ph.asset_id))
        specs = [{"hash": x.hash, "expectation": _j(x.data)} for x in s.scalars(select(SpecCache)).all()]
        sort_rows = _import_rows(s, org_id, project_id, since)
        assets = {a.id: a for a in s.scalars(select(Asset).where(
            Asset.id.in_(list(want_gens.values())[:MAX_IMAGES] + [a for _, a in want_refs]))).all()} if images != "none" else {}

    buf = io.BytesIO()
    skipped = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        z.writestr("checks.csv", _csv(checks, list(checks[0].keys()) if checks else ["check_id"]))
        z.writestr("reviews.csv", _csv(rev_rows, ["review_id", "created", "frame_id", "generation_id", "verdict",
                                                  "ai_verdict", "note_kind", "comment"]))
        z.writestr("profiles.csv", _csv(profiles, ["sku", "product", "category", "profile_version", "profile"]))
        z.writestr("references.csv", _csv(refs, ["sku", "view", "visible", "reference", "image"]))
        z.writestr("expectations.csv", _csv(specs, ["hash", "expectation"]))
        z.writestr("import_sort.csv", _csv(sort_rows, IMPORT_COLS))
        if images != "none":
            jobs = [(f"images/gen_{gid}.jpg", assets.get(aid)) for gid, aid in list(want_gens.items())[:MAX_IMAGES]]
            jobs += [(name, assets.get(aid)) for name, aid in want_refs]
            # картинки готовятся параллельно (декодирование PNG — самое долгое), в архив пишутся по порядку
            with ThreadPoolExecutor(4) as pool:
                for name, data in pool.map(_prepare, jobs):
                    if data is None:
                        skipped += 1
                    else:
                        z.writestr(name, data, compress_type=zipfile.ZIP_STORED)
    log.info("Выгрузка данных проверки: проверок %d, решений %d, картинок попыток %d%s", len(checks), len(rev_rows),
             min(len(want_gens), MAX_IMAGES), f", не найдено файлов {skipped}" if skipped else "")
    return buf.getvalue(), {"checks": len(checks), "reviews": len(rev_rows), "images": min(len(want_gens), MAX_IMAGES)}


IMPORT_COLS = ["session", "created", "client", "project", "options", "photo", "ai_role", "ai_group", "final_role",
               "final_group", "moved", "role_changed", "group_flagged", "article", "text", "product"]


def _import_rows(s, org_id, project_id, since):
    """Завершённые загрузки: что решил ИИ и что в итоге подтвердил пользователь."""
    q = (select(ImportFile, ImportSession, Project, Client)
         .join(ImportSession, ImportSession.id == ImportFile.session_id)
         .join(Project, Project.id == ImportSession.project_id)
         .join(Client, Client.id == Project.client_id)
         .where(Client.org_id == org_id, ImportSession.status == "done"))
    if project_id:
        q = q.where(Project.id == project_id)
    if since:
        q = q.where(ImportSession.created_at >= since)
    out = []
    for f, sess, pr, cl in s.execute(q.order_by(ImportSession.id, ImportFile.id)).all():
        a = f.analysis or {}
        if "final_role" not in a:          # загрузки до появления сравнения
            continue
        flagged = {x.get("name") for x in ((sess.result or {}).get("feedback") or {}).get("flagged") or []}
        out.append({"session": sess.id, "created": sess.created_at.isoformat(timespec="seconds") if sess.created_at else "",
                    "client": cl.name, "project": pr.name, "options": _j(sess.options), "photo": f.rel_path,
                    "ai_role": a.get("role", ""), "ai_group": a.get("ai_group") or "", "final_role": a.get("final_role", ""),
                    "final_group": a.get("final_group", ""), "moved": "да" if a.get("moved") else "",
                    "role_changed": "да" if a.get("role_changed") else "",
                    "group_flagged": "да" if a.get("final_group") in flagged else "", "article": a.get("article", ""),
                    "text": a.get("text", ""), "product": a.get("product", "")})
    return out


def _prepare(job):
    name, asset = job
    if asset is None:
        return name, None
    try:
        return name, _jpeg(storage.get(asset))
    except Exception as e:          # файл пропал или битый — выгрузка всё равно соберётся
        log.warning("Выгрузка проверки: картинка %s не добавлена: %s", name, e)
        return name, None
