"""Выдача клиенту: ZIP по артикулам + отчёт CSV."""
import csv
import io
import re
import zipfile
import uuid
from datetime import datetime

from sqlalchemy import func, select

from .. import db
from ..core import config, storage
from ..core.logs import log
from ..db.models import Frame, Generation, Product, Project, QCCheck, UsageEntry

STATUS_RU = {"pass": "прошёл ИИ-проверку", "accepted": "принят вручную", "review": "на ручной проверке",
             "unchecked": "без проверки", "missing": "не сгенерирован", "pending": "ждём результат"}
# «Только принятые»: принятые вручную, прошедшие ИИ-проверку и готовые кадры без проверки (когда она выключена)
ACCEPTED = ("pass", "accepted", "unchecked")
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name, fallback="без_артикула"):
    """Имя папки, которое откроется в Windows: без запрещённых символов, точек и пробелов в конце."""
    name = BAD_CHARS.sub("_", str(name or "")).strip().rstrip(". ")
    if name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                      *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name[:120] or fallback


def export_zip(project_id, include="accepted", frame_ids=None, product_ids=None):
    """ZIP: <артикул>/<NN>.png + report.csv. include: accepted (принятые, прошедшие проверку и без проверки) | all (все
    готовые) | picked (выделенные кадры frame_ids, любого статуса). product_ids — только эти товары.
    В report.csv — все кадры выгружаемых товаров, в том числе не попавшие в архив, с причиной."""
    frame_ids, product_ids = set(frame_ids or ()), set(product_ids or ())
    if include == "picked" and not frame_ids:
        raise ValueError("не выделено ни одного кадра")
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with db.session() as s:
        project = s.get(Project, project_id)
        q = (select(Product.id, Product.sku, Frame.position, Frame.status, Frame.block, Generation, Frame.id)
             .join(Frame, Frame.product_id == Product.id)
             .outerjoin(Generation, Generation.id == Frame.current_generation_id)
             .where(Product.project_id == project_id, Frame.status != "retired"))
        if include == "picked":         # кадры другого проекта в список не попадут: фильтр по проекту выше
            q = q.where(Frame.id.in_(frame_ids))
        elif product_ids:
            q = q.where(Product.id.in_(product_ids))
        rows = s.execute(q.order_by(func.lower(Product.sku), Product.id, Frame.position)).all()
        items, skipped, folders, used = [], [], {}, set()
        for pid, sku, pos, status, block, g, fid in rows:
            if pid not in folders:          # одинаковые артикулы у разных товаров — разные папки, а не перезапись
                base = safe_name(sku)
                name, n = base, 2
                while name.lower() in used:
                    name, n = f"{base}_{n}", n + 1
                used.add(name.lower())
                folders[pid] = name
            if g is None or g.status != "ok" or not g.output_asset_id:
                skipped.append((sku, pos, block, "нет готовой картинки" if g is None else
                                ("ждём результат Polza" if g.status == "pending" else "генерация не удалась")))
                continue
            allowed = {"accepted": ACCEPTED, "checked": ("pass", "accepted"), "manual": ("accepted",)}.get(include)
            if allowed and status not in allowed:
                skipped.append((sku, pos, block, STATUS_RU.get(status, status)))
                continue
            q = s.scalars(select(QCCheck).where(QCCheck.generation_id == g.id).order_by(QCCheck.id.desc()).limit(1)).first()
            cost = s.scalar(select(func.coalesce(func.sum(UsageEntry.amount_rub), 0)).where(UsageEntry.frame_id == fid))
            items.append((folders[pid], sku, pos, status, block, g.output_asset, g.model, q, float(cost or 0)))
        part = "_выделенные" if include == "picked" else ("_выбранные" if product_ids else "")
        name = safe_name(f"{project.client.name}_{project.name}{part}_{datetime.now():%Y%m%d-%H%M}".replace(" ", "_"), "export")
    path = config.EXPORT_DIR / f"{name}_{uuid.uuid4().hex[:12]}.zip"
    rep = io.StringIO()
    w = csv.writer(rep, delimiter=";")
    w.writerow(["артикул", "папка", "кадр", "в архиве", "статус", "блок", "модель", "проверка", "причины брака", "затраты, ₽"])
    done, failed = 0, []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for folder, sku, pos, status, block, asset, model, q, cost in items:
            ext = ".png" if asset.mime == "image/png" else ".jpg"
            try:
                data = storage.get(asset)
            except Exception as e:          # один недоступный файл не должен обрывать всю выгрузку
                log.error("Выгрузка: не удалось прочитать кадр %s #%02d из хранилища: %s", sku, pos, e)
                failed.append((sku, pos, block, f"файл не прочитан из хранилища: {str(e)[:120]}"))
                continue
            z.writestr(f"{folder}/{pos:02d}{ext}", data)
            done += 1
            w.writerow([sku, folder, f"{pos:02d}", "да", STATUS_RU.get(status, status), block, model,
                        q.model if q else "", "; ".join(q.reasons) if q else "", f"{cost:.2f}"])
        for sku, pos, block, why in skipped + failed:
            w.writerow([sku, "", f"{pos:02d}", "нет — " + why, "", block, "", "", "", ""])
        z.writestr("report.csv", "\ufeff" + rep.getvalue())
    log.info("Выгрузка проекта %s: в архиве %d кадров, не попало %d (из них ошибок чтения %d) → %s",
             project_id, done, len(skipped) + len(failed), len(failed), path)
    return path, done

