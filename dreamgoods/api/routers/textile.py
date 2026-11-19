"""Перенос ткани по двум фото через очередь генерации."""
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from ... import db
from ...core import storage
from ...db.models import Asset, Job
from ...services import plans, textile
from ..deps import need_key, project_id

router = APIRouter(prefix="/api/projects/{project_id}/textile", tags=["перенос ткани"])


@router.post("")
async def start(photo: UploadFile, fabric: UploadFile, pid: int = Depends(project_id)):
    await run_in_threadpool(need_key, pid)
    await run_in_threadpool(plans.check_storage_project, pid)
    maximum = textile.MAX_IMAGE_BYTES
    return await run_in_threadpool(
        textile.start, pid, await photo.read(maximum + 1), await fabric.read(maximum + 1),
    )


@router.get("")
def latest(pid: int = Depends(project_id)):
    return {"job": textile.latest(pid)}


@router.get("/{job_id}/image")
def image(job_id: int, download: bool = False, pid: int = Depends(project_id)):
    with db.session() as s:
        job = s.get(Job, job_id)
        result = (job.payload or {}).get("output") if job and job.project_id == pid and job.kind == "textile" else None
        asset = s.get(Asset, UUID(result)) if result else None
        if not asset:
            raise LookupError("Результат переноса ткани не найден")
        headers = {"Cache-Control": "private, max-age=3600"}
        if download:
            ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(asset.mime, "png")
            headers["Content-Disposition"] = f'attachment; filename="textile-transfer.{ext}"'
        return Response(storage.get(asset), media_type=asset.mime, headers=headers)
