"""Задания переноса ткани и проверка входных фото."""
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from .. import db
from ..core import storage
from ..core.events import utcnow
from ..db.models import Job, Project
from ..workers.queue import ACTIVE, enqueue

MAX_IMAGE_BYTES = 20 * 1024 * 1024


def validate_photo(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Загрузите изображение размером до 20 МБ")
    try:
        with Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as photo:
            if photo.width * photo.height > 16_000_000:
                raise ValueError("Размер изображения должен быть не больше 16 мегапикселей")
            photo.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Загрузите читаемое изображение JPEG, PNG или WebP") from exc


def _view(job):
    return {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "has_image": job.status == "done" and bool((job.payload or {}).get("output")),
    }


def latest(project_id):
    jobs = select(Job).where(Job.project_id == project_id, Job.kind == "textile").order_by(Job.id.desc()).limit(1)
    with db.session() as s:
        job = s.scalar(jobs)
        current = _view(job) if job else None
        if current is None or current["has_image"]:
            return {"job": current, "result_id": job.id if job else None}
        previous_id = s.scalar(jobs.with_only_columns(Job.id).where(
            Job.status == "done", Job.payload["output"].as_string().is_not(None),
        ))
        return {"job": current, "result_id": previous_id}


def start(project_id, photo, fabric, prompt=""):
    validate_photo(photo)
    validate_photo(fabric)
    with db.session() as s:
        project = s.get(Project, project_id, with_for_update=True)
        active = s.scalar(select(Job).where(
            Job.project_id == project_id, Job.kind == "textile", Job.status.in_(ACTIVE),
        ).order_by(Job.id.desc()).limit(1))
        if active:
            return _view(active)
        org_id = project.client.org_id
        garment = storage.put(s, org_id, photo, "textile", "garment")
        swatch = storage.put(s, org_id, fabric, "textile", "swatch")
        return _view(enqueue(s, "textile", project_id, payload={
            "photo": str(garment.id), "fabric": str(swatch.id), "prompt": prompt.strip(),
        }))


def cancel(project_id, job_id):
    with db.session() as s:
        job = s.scalar(select(Job).where(Job.id == job_id, Job.project_id == project_id, Job.kind == "textile")
                       .with_for_update())
        if job is None:
            raise LookupError("Задание переноса ткани не найдено")
        if job.status in ("queued", "paused"):
            job.status, job.finished_at = "cancelled", utcnow()
            job.error = ""
        elif job.status == "running":
            job.status = "cancelling"
        return _view(job)
