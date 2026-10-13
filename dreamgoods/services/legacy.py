"""Перенос данных из прежней версии (папки ShoesEdit) в PostgreSQL + S3.

Что переносится:
  Сортированное/<артикул>/*.jpg        → товары и фото (ваш выбор референсов сохраняется), _labels → этикетки
  <артикул>/_label.json, _profile.json → данные этикеток, профиль товара
  <артикул>/_frames.json или таблица промптов CSV → кадры с промптами
  results/<артикул>/NN.png, _qc.json   → текущие результаты с итогами проверки
  results/<артикул>/_rejected, _archive → история: брак и прежние варианты
  results/qc_labels.csv                → ваша ручная разметка с комментариями (заметки для проверки)
  results/studio_log.csv               → журнал расходов
  studio_settings.json                 → настройки проекта и ключ Polza
Повторный запуск не создаёт дублей: уже перенесённые артикулы пропускаются.
"""
import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .. import db
from ..ai import prompts
from ..core import storage
from ..core.logs import log
from ..db.models import (Frame, Generation, Organization, Product, ProductPhoto, ProductProfile, Project, QCCheck, Review,
                     UsageEntry)
from ..core.settings import DEFAULTS, clean

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _read_text(p):
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def _json(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _ts(p):
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)


def _dt(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").astimezone(timezone.utc)
    except Exception:
        return None


def _csv_prompts(path):
    if not path or not path.is_file():
        return {}
    text = _read_text(path)
    first = text.splitlines()[0] if text.strip() else "folder;prompt"
    try:
        delim = csv.Sniffer().sniff(first, delimiters=";,\t").delimiter
    except csv.Error:
        delim = ";"
    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if row.get("folder") and row.get("prompt"):
            out.setdefault(row["folder"].lower(), []).append(row["prompt"])
    return out


def find_legacy(root):
    """Папка прежней версии: где лежит studio_settings.json (рядом с проектом или уровнем выше)."""
    for d in (root, root.parent):
        if (d / "studio_settings.json").is_file():
            return d
    return None


def run(base, project_id=None):
    base = Path(base)
    st = _json(base / "studio_settings.json", {}) or {}
    inp = Path(st.get("input_root") or base / "Сортированное")
    out = Path(st.get("output_root") or base / "results")
    csv_prompts = _csv_prompts(Path(st.get("prompts_csv") or base / "prompts_sapogi.csv"))
    refs_sel = st.get("refs") or {}
    max_refs = int(st.get("max_refs") or 6)
    if not inp.is_dir():
        raise RuntimeError(f"не найдена папка с референсами прежней версии: {inp}")
    log.info("Перенос из %s: референсы %s, результаты %s", base, inp, out)
    stats = dict(products=0, photos=0, labels=0, profiles=0, frames=0, outputs=0, history=0, reviews=0, usage=0, skipped=0)

    with db.session() as s:
        project = s.get(Project, project_id) if project_id else s.scalars(select(Project).order_by(Project.id)).first()
        org = s.get(Organization, project.client.org_id)
        org_id, project_id = org.id, project.id
        # настройки: проект + ключи организации
        vals = clean({k: v for k, v in st.items() if k in DEFAULTS})
        project.settings = {**vals, **(project.settings or {})}
        key = (st.get("api_key") or "").strip()
        if not key and st.get("node_config"):
            key = ((_json(Path(st["node_config"]), {}) or {}).get("api_key") or "").strip()
        secrets = {k: v for k, v in (("api_key", key), ("qc_api_key", (st.get("qc_api_key") or "").strip())) if v}
        if secrets:
            org.settings = {**(org.settings or {}), **{k: v for k, v in secrets.items() if not (org.settings or {}).get(k)}}

    frame_index = {}   # (артикул в нижнем регистре, позиция) → (frame_id, product_id, текущая генерация, mtime файла)
    for d in sorted((p for p in inp.iterdir() if p.is_dir() and not p.name.startswith("_")), key=lambda p: p.name.lower()):
        with db.session() as s:
            if s.scalar(select(Product.id).where(Product.project_id == project_id, Product.sku == d.name)):
                stats["skipped"] += 1
                log.info("Перенос: %s уже есть в базе — пропуск", d.name)
                continue
        _product(d, out / d.name, project_id, org_id, refs_sel.get(d.name), max_refs, csv_prompts.get(d.name.lower()),
                 frame_index, stats)

    # ручная разметка
    labels = out / "qc_labels.csv"
    if labels.is_file():
        with db.session() as s:
            for row in csv.reader(io.StringIO(_read_text(labels)), delimiter=";"):
                if len(row) < 7:
                    continue
                ts, folder, i, mtime, ai, _ai_min, human = row[:7]
                comment = row[7] if len(row) > 7 else ""
                try:
                    fr = frame_index.get((folder.lower(), int(i)))
                except ValueError:
                    continue
                if not fr or human not in ("ok", "bad"):
                    continue
                frame_id, _pid, gen_id, file_mtime = fr
                gid = gen_id if gen_id and str(file_mtime) == mtime.strip() else None
                kind = ""
                if comment:
                    kind = ("false_alarm" if ai == "fail" and human == "ok" else
                            "missed" if ai == "pass" and human == "bad" else "note")
                s.add(Review(frame_id=frame_id, generation_id=gid, verdict=human, ai_verdict=ai if ai in ("pass", "fail") else "",
                             comment=comment, note_kind=kind, created_at=_dt(ts) or datetime.now(timezone.utc)))
                stats["reviews"] += 1

    # журнал расходов
    journal = out / "studio_log.csv"
    if journal.is_file():
        with db.session() as s:
            prods = {p.sku.lower(): p.id for p in s.scalars(select(Product).where(Product.project_id == project_id)).all()}
            for row in csv.reader(io.StringIO(_read_text(journal)), delimiter=";"):
                if len(row) < 7 or row[3] not in ("ok", "qc"):
                    continue
                try:
                    amount = float(row[6] or 0)
                except ValueError:
                    continue
                extra = row[7] if len(row) > 7 else ""
                kind = "generation" if row[3] == "ok" else "profile" if extra.startswith("profile") else \
                    "sort" if extra.startswith("import") else "qc"
                fr = frame_index.get((row[1].lower(), int(row[2]) if row[2].isdigit() else -1))
                s.add(UsageEntry(org_id=org_id, project_id=project_id, product_id=prods.get(row[1].lower()),
                                 frame_id=fr[0] if fr else None, kind=kind, model=row[4], provider=row[5], amount_rub=amount,
                                 ref="legacy", created_at=_dt(row[0]) or datetime.now(timezone.utc)))
                stats["usage"] += 1

    with db.session() as s:
        org = s.get(Organization, org_id)
        org.settings = {**(org.settings or {}), "legacy_imported": str(base)}
    log.info("Перенос завершён: %s", ", ".join(f"{k} {v}" for k, v in stats.items()))
    return stats


def _product(d, res_dir, project_id, org_id, selected, max_refs, csv_rows, frame_index, stats):
    imgs = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT)
    labs = sorted(p for p in (d / "_labels").iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT) \
        if (d / "_labels").is_dir() else []
    chosen = set(selected) if selected is not None else {p.name for p in imgs[:max_refs]}
    prof = _json(d / "_profile.json")
    label = _json(d / "_label.json", {}) or {}
    frames_json = _json(d / "_frames.json")
    if isinstance(frames_json, dict):
        prompts_list, edited = frames_json.get("prompts") or [], set(frames_json.get("edited") or [])
    else:
        prompts_list, edited = frames_json or csv_rows or [], set()
    qc_map = _json(res_dir / "_qc.json", {}) or {}

    with db.session() as s:
        p = Product(project_id=project_id, sku=d.name, label_data={"articles": label.get("articles") or [],
                                                                   "texts": label.get("texts") or []})
        s.add(p)
        s.flush()
        stats["products"] += 1
        for n, f in enumerate(imgs, 1):
            a = storage.put(s, org_id, f.read_bytes(), "photo", f.name)
            s.add(ProductPhoto(product_id=p.id, asset_id=a.id, role="product", is_reference=f.name in chosen, position=n))
            stats["photos"] += 1
        for n, f in enumerate(labs, len(imgs) + 1):
            a = storage.put(s, org_id, f.read_bytes(), "photo", f.name)
            s.add(ProductPhoto(product_id=p.id, asset_id=a.id, role="label", is_reference=False, position=n))
            stats["labels"] += 1
        if prof:
            meta = {k: prof.pop(k, None) for k in ("made_by", "made_at", "refs", "cost", "edited_at")}
            pp = ProductProfile(product_id=p.id, version=1, data=prof, source="legacy", model=meta.get("made_by") or "",
                                cost_rub=float(meta.get("cost") or 0))
            s.add(pp)
            s.flush()
            p.current_profile_id, p.category = pp.id, prof.get("category") or ""
            stats["profiles"] += 1
        if not prompts_list and prof:
            prompts_list = prompts.build_prompts(prof)
        for i, text in enumerate(prompts_list, 1):
            fr = Frame(product_id=p.id, position=i, prompt=text, prompt_source="legacy", prompt_edited=i in edited,
                       block=prompts.block_of(text), status="missing")
            s.add(fr)
            s.flush()
            stats["frames"] += 1
            # история: брак и архив этого кадра
            for sub, outcome in (("_archive", "archived"), ("_rejected", "rejected")):
                hd = res_dir / sub
                if not hd.is_dir():
                    continue
                for hf in sorted(hd.glob(f"{i:02d}_*.png")):
                    a = storage.put(s, org_id, hf.read_bytes(), "output", hf.name)
                    s.add(Generation(frame_id=fr.id, attempt=0, prompt=text, status="ok", output_asset_id=a.id,
                                     outcome=outcome, created_at=_ts(hf)))
                    stats["history"] += 1
            cur = res_dir / f"{i:02d}.png"
            gen_id, mtime = None, None
            if cur.is_file():
                mtime = int(cur.stat().st_mtime)
                e = qc_map.get(f"{i:02d}") or {}
                a = storage.put(s, org_id, cur.read_bytes(), "output", f"{d.name}_{i:02d}.png")
                g = Generation(frame_id=fr.id, attempt=int(e.get("attempts") or 1) if e.get("img_mtime") == mtime else 1,
                               model=e.get("model") or "", provider=e.get("provider") or "", prompt=text, status="ok",
                               output_asset_id=a.id, outcome="current", cost_rub=0.0, created_at=_ts(cur))
                s.add(g)
                s.flush()
                gen_id = g.id
                fr.current_generation_id = g.id
                stats["outputs"] += 1
                if e and e.get("img_mtime") == mtime and e.get("status") not in (None, "unchecked", "rejected"):
                    reasons = [x for x in re.split(r";\s*", e.get("defects") or "") if x and not x.startswith("мелочи")]
                    if e.get("ai") in ("pass", "fail"):
                        s.add(QCCheck(frame_id=fr.id, generation_id=g.id, model=e.get("qc_model") or "",
                                      passed=e.get("ai") == "pass", reasons=reasons, tech=e.get("tech") or [],
                                      counts=e.get("counts"), info=e.get("info") or {}, source="legacy"))
                    fr.status = e["status"] if e["status"] in ("pass", "review", "accepted") else "unchecked"
                else:
                    fr.status = "unchecked"
            elif (qc_map.get(f"{i:02d}") or {}).get("status") == "rejected":
                fr.status = "rejected"
            frame_index[(d.name.lower(), i)] = (fr.id, p.id, gen_id, mtime)
    log.info("Перенос: %s — фото %d, этикеток %d, кадров %d%s", d.name, len(imgs), len(labs), len(prompts_list),
             ", профиль" if prof else "")
