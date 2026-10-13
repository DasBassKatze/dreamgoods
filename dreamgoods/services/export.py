"""Выдача клиенту: ZIP по артикулам + отчёт CSV."""
import csv
import io
import zipfile
from datetime import datetime

from sqlalchemy import func, select

from .. import db
from ..core import config, storage
from ..core.logs import log
from ..db.models import Frame, Generation, Product, Project, QCCheck, UsageEntry

STATUS_RU = {"pass": "прошёл ИИ-проверку", "accepted": "принят вручную", "review": "на ручной проверке",
             "unchecked": "без проверки"}


def export_zip(project_id, include="accepted"):
    """ZIP: <артикул>/<NN>.png + report.csv. include: accepted (принятые и прошедшие проверку) | all (все готовые)."""
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with db.session() as s:
        project = s.get(Project, project_id)
        rows = s.execute(select(Product.sku, Frame.position, Frame.status, Frame.block, Generation, Frame.id)
                         .join(Frame, Frame.product_id == Product.id)
                         .join(Generation, Generation.id == Frame.current_generation_id)
                         .where(Product.project_id == project_id).order_by(func.lower(Product.sku), Frame.position)).all()
        items = []
        for sku, pos, status, block, g, fid in rows:
            if include == "accepted" and status not in ("pass", "accepted"):
                continue
            q = s.scalars(select(QCCheck).where(QCCheck.generation_id == g.id).order_by(QCCheck.id.desc()).limit(1)).first()
            cost = s.scalar(select(func.coalesce(func.sum(UsageEntry.amount_rub), 0)).where(UsageEntry.frame_id == fid))
            items.append((sku, pos, status, block, g.output_asset, g.model, q, float(cost or 0)))
        name = f"{project.client.name}_{project.name}_{datetime.now():%Y%m%d-%H%M}".replace(" ", "_")
    path = config.EXPORT_DIR / f"{name}.zip"
    rep = io.StringIO()
    w = csv.writer(rep, delimiter=";")
    w.writerow(["артикул", "кадр", "статус", "блок", "модель", "проверка", "причины брака", "затраты, ₽"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for sku, pos, status, block, asset, model, q, cost in items:
            ext = ".png" if asset.mime == "image/png" else ".jpg"
            z.writestr(f"{sku}/{pos:02d}{ext}", storage.get(asset))
            w.writerow([sku, f"{pos:02d}", STATUS_RU.get(status, status), block, model,
                        q.model if q else "", "; ".join(q.reasons) if q else "", f"{cost:.2f}"])
        z.writestr("report.csv", "﻿" + rep.getvalue())
    log.info("Выгрузка проекта %s: %d кадров → %s", project_id, len(items), path)
    return path, len(items)
