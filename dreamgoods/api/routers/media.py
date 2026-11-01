"""Файлы и выгрузка."""
import uuid

from fastapi import APIRouter, Depends, Request
from typing import Literal
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, Response

from ... import db
from ...core import auth, storage
from ...db.models import Asset
from ...services import access, export
from ..deps import project_id

router = APIRouter(tags=["файлы"])
CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}   # файлы не меняются; private — не в общих кэшах


@router.get("/api/assets/{asset_id}")
def asset(asset_id: uuid.UUID, request: Request, w: int = 0):
    """Оригинал (w=0) или JPEG-превью шириной до w px. Только файлы своего кабинета."""
    if not access.asset_allowed(auth.user(request), asset_id):
        raise LookupError("файл не найден")
    with db.session() as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise LookupError("файл не найден")
        s.expunge(a)
    if w <= 0:
        return Response(storage.get(a), media_type=a.mime, headers=CACHE)
    return Response(storage.thumb(a, min(w, 1600)), media_type="image/jpeg", headers=CACHE)


@router.get("/api/projects/{project_id}/export")
def export_zip(include: Literal["accepted", "all"] = "accepted", output_format: Literal["original", "jpeg", "png"] = "original",
               require_complete: bool = False, pid: int = Depends(project_id)):
    """ZIP по артикулам + report.csv. include=accepted — только принятые, all — все готовые."""
    path, _ = export.export_zip(pid, include, output_format, require_complete)
    return FileResponse(path, media_type="application/zip", filename=path.name, background=BackgroundTask(path.unlink, missing_ok=True))

