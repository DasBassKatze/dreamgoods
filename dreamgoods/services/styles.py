"""Референсы оформления клиента: фото-пример стиля + что в нём нравится → разбор стиля ИИ → применение к кадрам."""
from sqlalchemy import func, select

from .. import db
from ..ai.styleref import BLOCKS_RU, DEFAULT_BLOCKS
from ..core import storage
from ..core.events import say
from ..db.models import Job, Product, Project, StyleRef, StyleRefPhoto
from ..workers.queue import enqueue
from .common import LIVE, org_of_project, product_in


def _project(s, project_id):
    p = s.get(Project, project_id)
    if not p:
        raise LookupError("проект не найден")
    return p


def _ref(s, project_id, ref_id):
    project = _project(s, project_id)
    r = s.get(StyleRef, int(ref_id))
    if not r or r.client_id != project.client_id or r.status == "archived":
        raise LookupError("референс оформления не найден")
    return r


def _blocks(v):
    v = [b for b in (v or []) if b in BLOCKS_RU]
    return v or list(DEFAULT_BLOCKS)


def listing(project_id):
    with db.session() as s:
        project = _project(s, project_id)
        default = int((project.settings or {}).get("style_ref_id") or 0)
        refs = s.scalars(select(StyleRef).where(StyleRef.client_id == project.client_id, StyleRef.status != "archived")
                         .order_by(StyleRef.id)).all()
        ids = [r.id for r in refs]
        photos = s.scalars(select(StyleRefPhoto).where(StyleRefPhoto.style_ref_id.in_(ids))
                           .order_by(StyleRefPhoto.position, StyleRefPhoto.id)).all() if ids else []
        used = dict(s.execute(select(Product.style_ref_id, func.count(Product.id))
                              .where(Product.project_id == project_id, Product.style_ref_id.in_(ids))
                              .group_by(Product.style_ref_id)).all()) if ids else {}
        jobs = {}
        for j in s.scalars(select(Job).where(Job.kind == "styleref", Job.project_id == project_id,
                                             Job.status.in_(LIVE + ("error",))).order_by(Job.id)).all():
            jobs[int((j.payload or {}).get("style_ref_id") or 0)] = j
        by = {}
        for ph in photos:
            by.setdefault(ph.style_ref_id, []).append({"id": ph.id, "asset": str(ph.asset_id)})
        out = []
        for r in refs:
            j = jobs.get(r.id)
            out.append({"id": r.id, "name": r.name, "note": r.note, "description": r.description, "blocks": _blocks(r.blocks),
                        "status": r.status, "photos": by.get(r.id, []), "products": used.get(r.id, 0),
                        "is_default": r.id == default,
                        "job": None if not j else {"state": "error" if j.status in ("error", "paused") else "running", "error": j.error}})
        return {"refs": out, "default_id": default if default in ids else 0,
                "blocks": [{"key": k, "name": v} for k, v in BLOCKS_RU.items()]}


def create(project_id, name, note, blocks):
    with db.session() as s:
        project = _project(s, project_id)
        from .plans import check_new_style
        check_new_style(s, project.client)
        r = StyleRef(client_id=project.client_id, name=(name or "").strip()[:120] or "Новое оформление",
                     note=(note or "").strip(), blocks=_blocks(blocks), status="draft")
        s.add(r)
        s.flush()
        return r.id


def update(project_id, ref_id, values):
    with db.session() as s:
        r = _ref(s, project_id, ref_id)
        if values.get("name") is not None and str(values["name"]).strip():
            r.name = str(values["name"]).strip()[:120]
        for k in ("note", "description"):
            if values.get(k) is not None:
                setattr(r, k, str(values[k]).strip())
        if values.get("blocks") is not None:
            r.blocks = _blocks(values["blocks"])
        if r.status == "draft" and r.description and _count(s, r.id):
            r.status = "ready"


def _count(s, ref_id):
    return s.scalar(select(func.count(StyleRefPhoto.id)).where(StyleRefPhoto.style_ref_id == ref_id)) or 0


def upload_photo(project_id, ref_id, data, filename):
    import io
    from PIL import Image, UnidentifiedImageError
    if not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("размер референса: не больше 20 МБ")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 40_000_000:
                raise ValueError("референс слишком большой: максимум 40 мегапикселей")
            im.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValueError("не удалось прочитать изображение референса") from e
    with db.session() as s:
        r = _ref(s, project_id, ref_id)
        if _count(s, r.id) >= 3:
            raise ValueError("не больше 3 фото в одном референсе")
        a = storage.put(s, org_of_project(s, project_id).id, data, "style", filename)
        if not (a.mime or "").startswith("image/"):
            raise ValueError("это не картинка")
        pos = (s.scalar(select(func.max(StyleRefPhoto.position)).where(StyleRefPhoto.style_ref_id == r.id)) or 0) + 1
        s.add(StyleRefPhoto(style_ref_id=r.id, asset_id=a.id, position=pos))
    return {"ok": True}


def delete_photo(project_id, ref_id, photo_id):
    with db.session() as s:
        r = _ref(s, project_id, ref_id)
        ph = s.get(StyleRefPhoto, int(photo_id))
        if not ph or ph.style_ref_id != r.id:
            raise LookupError("фото не найдено")
        s.delete(ph)
        s.flush()
        if not _count(s, r.id):
            r.status = "draft"


def describe(project_id, ref_id):
    """ИИ разбирает стиль по фото и пожеланию клиента."""
    with db.session() as s:
        r = _ref(s, project_id, ref_id)
        s.refresh(r, with_for_update=True)
        if not _count(s, r.id):
            raise ValueError("сначала загрузите фото-пример")
        active = s.scalars(select(Job).where(Job.kind == "styleref", Job.status.in_(LIVE),
                                            Job.payload["style_ref_id"].as_integer() == r.id)).all()
        if any(j.status != "paused" for j in active):
            raise ValueError("разбор уже идёт")
        # A denied budget reserve sent no provider request. Retry only after an
        # explicit paid click; do not leave the reference spinning indefinitely.
        for j in active:
            j.status = "cancelled"
        s.flush()
        enqueue(s, "styleref", project_id, payload={"style_ref_id": r.id}, priority=15)


def archive(project_id, ref_id):
    with db.session() as s:
        r = _ref(s, project_id, ref_id)
        r.status = "archived"
        for pr in s.scalars(select(Project).where(Project.client_id == r.client_id)).all():
            if int((pr.settings or {}).get("style_ref_id") or 0) == r.id:
                pr.settings = {**pr.settings, "style_ref_id": 0}
        s.query(Product).filter(Product.style_ref_id == r.id).update({Product.style_ref_id: None})


def set_project_default(project_id, ref_id):
    with db.session() as s:
        project = _project(s, project_id)
        if ref_id:
            r = _ref(s, project_id, ref_id)
            if r.status != "ready":
                raise ValueError("референс ещё не готов: нужны фото и разбор стиля")
        project.settings = {**(project.settings or {}), "style_ref_id": int(ref_id or 0)}
        name = r.name if ref_id else ""
    say("info", f"🎨 Оформление проекта: {name or 'без референса'}", project_id)


def set_product(project_id, product_id, ref_id):
    with db.session() as s:
        pr = product_in(s, project_id, product_id)
        if ref_id:
            _ref(s, project_id, ref_id)
        pr.style_ref_id = int(ref_id) if ref_id else None

