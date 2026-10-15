"""Файлы и выгрузка."""
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from ... import db
from ...core import auth, storage
from ...db.models import Asset
from ...services import access, export
from ..deps import project_id

router = APIRouter(tags=["файлы"])
CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}   # файлы не меняются; private — не в общих кэшах


@router.get("/api/assets/{asset_id}")
def asset(asset_id: uuid.UUID, request: Request, w: int = 0, dl: str = ""):
    """Оригинал (w=0) или JPEG-превью шириной до w px. Только файлы своего кабинета.
    dl — скачать оригинал файлом с этим именем (расширение — по типу файла)."""
    if not access.asset_allowed(auth.user(request), asset_id):
        raise LookupError("файл не найден")
    with db.session() as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise LookupError("файл не найден")
        s.expunge(a)
    if dl:
        ext = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg"}.get(a.mime, "")
        name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in dl)[:80] or "frame"
        return Response(storage.get(a), media_type=a.mime,
                        headers={**CACHE, "Content-Disposition": f'attachment; filename="{name}{ext}"'})
    if w <= 0:
        return Response(storage.get(a), media_type=a.mime, headers=CACHE)
    return Response(storage.thumb(a, min(w, 1600)), media_type="image/jpeg", headers=CACHE)


@router.get("/api/projects/{project_id}/export")
def export_zip(include: str = "accepted", frames: str = "", products: str = "", pid: int = Depends(project_id)):
    """ZIP по артикулам + report.csv. include=accepted — принятые, all — все готовые, picked — выделенные кадры (frames).
    frames, products — номера через запятую: только эти кадры / только эти товары."""
    def ids(v):
        return {int(x) for x in v.split(",") if x.strip().isdigit()}
    include = include if include in ("accepted", "all", "picked") else "accepted"
    path, _ = export.export_zip(pid, include, frame_ids=ids(frames), product_ids=ids(products))
    return FileResponse(path, media_type="application/zip", filename=path.name)
