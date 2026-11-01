"""Выдача клиенту: ZIP по артикулам + отчёт CSV."""
import csv
import io
import zipfile
from datetime import datetime
from uuid import uuid4
import re
from PIL import Image, ImageOps
from .common import context
from ..core import presets

from sqlalchemy import func, select

from .. import db
from ..core import config, storage
from ..core.logs import log
from ..db.models import Frame, Generation, Product, Project, QCCheck, UsageEntry

STATUS_RU = {"pass": "прошёл ИИ-проверку", "accepted": "принят вручную", "review": "на ручной проверке",
             "unchecked": "без проверки"}


def export_zip(project_id, include="accepted", output_format="original", require_complete=False):
    """ZIP: <артикул>/<NN>.png + report.csv. include: accepted (принятые и прошедшие проверку) | all (все готовые)."""
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with db.session() as s:
        project = s.get(Project, project_id)
        rows = s.execute(select(Product.sku, Frame.position, Frame.status, Frame.block, Generation, Frame.id)
                         .join(Frame, Frame.product_id == Product.id)
                         .join(Generation, Generation.id == Frame.current_generation_id)
                         .where(Product.project_id == project_id).order_by(func.lower(Product.sku), Frame.position)).all()
        items = []
        complete = {}
        for sku, pos, status, block, g, fid in rows:
            complete[sku] = complete.get(sku, True) and status in ("pass", "accepted")
        manifest = []
        for sku, pos, status, block, g, fid in rows:
            if include == "accepted" and status not in ("pass", "accepted"):
                continue
            if require_complete and not complete[sku]:
                continue
            frame = s.get(Frame, fid)
            product = s.get(Product, frame.product_id)
            st = context(s, product)[2]
            q = s.scalars(select(QCCheck).where(QCCheck.generation_id == g.id).order_by(QCCheck.id.desc()).limit(1)).first()
            cost = s.scalar(select(func.coalesce(func.sum(UsageEntry.amount_rub), 0)).where(UsageEntry.frame_id == fid))
            items.append((sku, pos, status, block, g.output_asset, g.model, q, float(cost or 0), st))
        name = f"{project.client.name}_{project.name}_{datetime.now():%Y%m%d-%H%M}".replace(" ", "_")
    name = safe_name(name)
    path = config.EXPORT_DIR / f"{name}_{uuid4().hex[:12]}.zip"
    rep = io.StringIO()
    w = csv.writer(rep, delimiter=";")
    w.writerow(["артикул", "кадр", "статус", "блок", "модель", "проверка", "причины брака", "затраты, ₽"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for sku, pos, status, block, asset, model, q, cost, st in items:
            ext = ".png" if asset.mime == "image/png" else ".jpg"
            data = storage.get(asset)
            issues = []
            if output_format != "original":
                data, ext, issues = convert_image(data, st, output_format)
            folder = safe_name(sku)
            # Hash prevents different unsafe SKUs collapsing to the same folder.
            if folder != sku:
                import hashlib
                folder += "_" + hashlib.sha256(sku.encode()).hexdigest()[:8]
            filename = f"{folder}/{pos:02d}{ext}"
            z.writestr(filename, data)
            manifest.append({"sku": sku, "file": filename, "position": pos, "cover": pos == 1,
                "complete": complete[sku], "format": output_format, "warnings": issues})
            w.writerow([sku, f"{pos:02d}", STATUS_RU.get(status, status), block, model,
                        q.model if q else "", "; ".join(q.reasons) if q else "", f"{cost:.2f}"])
        import json
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr("report.csv", "﻿" + rep.getvalue())
    log.info("Выгрузка проекта %s: %d кадров → %s", project_id, len(items), path)
    return path, len(items)



def safe_name(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")[:150] or "item"


def convert_image(data, st, output_format):
    if output_format not in ("jpeg", "png"):
        raise ValueError("неизвестный формат экспорта")
    warnings = []
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        aspect = str(st.get("aspect") or "3:4").split(":")
        ratio = float(aspect[0]) / float(aspect[1]) if len(aspect) == 2 else im.width / im.height
        min_side = max(1, min(4096, int(st.get("qc_min_side") or 900)))
        width, height = (min_side, round(min_side / ratio)) if ratio <= 1 else (round(min_side * ratio), min_side)
        scale = max(1, min(im.width / width, im.height / height))
        width, height = min(8192, round(width * scale)), min(8192, round(height * scale))
        if im.width < min_side or im.height < min_side:
            warnings.append("исходник меньше минимального размера; увеличение не восстанавливает детали")
        im.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(im, ((width-im.width)//2, (height-im.height)//2), im)
        out = io.BytesIO()
        canvas.save(out, "JPEG" if output_format == "jpeg" else "PNG", **({"quality":95} if output_format == "jpeg" else {}))
        return out.getvalue(), ".jpg" if output_format == "jpeg" else ".png", warnings
