"""Задания переноса ткани и проверка входных фото."""
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from .. import db
from ..core import storage
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
        "has_image": bool((job.payload or {}).get("output")),
    }


def latest(project_id):
    with db.session() as s:
        job = s.scalar(select(Job).where(Job.project_id == project_id, Job.kind == "textile")
                       .order_by(Job.id.desc()).limit(1))
        return _view(job) if job else None


def start(project_id, photo, fabric):
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
            "photo": str(garment.id), "fabric": str(swatch.id),
        }))
