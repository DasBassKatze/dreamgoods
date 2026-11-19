"""ИИ-рематериализация одежды с сохранением исходной сцены."""
from uuid import UUID

from .. import db
from ..ai import polza
from ..ai.images import ref_for
from ..core import presets, storage
from ..core.settings import effective
from ..db.models import Asset, Job, Organization, Project
from .queue import set_note

PROMPT = (
    "Edit the first image. Use the second image only as the exact fabric reference. "
    "Identify the main garment in the first image and replace only its textile color and pattern. "
    "Match the swatch's colors, motif, spacing and proportions at a realistic scale. "
    "Make the pattern follow the garment's surface, seams, folds and perspective. "
    "Preserve the original garment silhouette, construction, fit, fabric texture, shadows and highlights. "
    "Keep the person, pose, skin, hair, accessories, other clothing, background, lighting, "
    "composition and crop from the first image. Respect occlusions. Do not add text, extra garments, "
    "or any part of the swatch photo as an object. Return only the edited photograph."
)


def handle(job_id):
    set_note(job_id, "ИИ переносит ткань")
    with db.session() as s:
        job = s.get(Job, job_id)
        project = s.get(Project, job.project_id)
        org = s.get(Organization, project.client.org_id)
        org_id = org.id
        st = effective(org, project)
        photo = s.get(Asset, UUID(job.payload["photo"]))
        fabric = s.get(Asset, UUID(job.payload["fabric"]))
        # Сохраняем композицию исходного снимка независимо от формата проекта.
        st["aspect"] = polza.nearest_aspect(f"{photo.width}:{photo.height}", presets.ASPECTS)
        side = int(st.get("ref_side") or 1536)
    answer = polza.generate(st, st["api_key"], PROMPT, [ref_for(photo, side), ref_for(fabric, side)], "[перенос ткани]")
    img = polza.extract_image(answer)
    if not img:
        raise RuntimeError("Polza не вернула изображение")
    with db.session() as s:
        job = s.get(Job, job_id)
        out = storage.put(s, org_id, img, "textile", "textile-transfer")
        job.payload = {**job.payload, "output": str(out.id)}
