"""Задание «styleref»: ИИ разбирает стиль по фото-примеру оформления и пожеланию клиента."""
from sqlalchemy import select

from .. import db
from ..ai import styleref
from ..core import storage
from ..core.events import say
from ..core.logs import Trace
from ..core.settings import effective
from ..db.models import Job, Organization, Project, StyleRef, StyleRefPhoto
from ..services import moderation
from ..services.common import write_usage
from .queue import set_note


def handle(job_id):
    with db.session() as s:
        job = s.get(Job, job_id)
        project = s.get(Project, job.project_id)
        org = s.get(Organization, project.client.org_id)
        st, org_id, project_id = effective(org, project), org.id, project.id
        r = s.get(StyleRef, int(job.payload["style_ref_id"]))
        rid, note, name = r.id, r.note, r.name
        assets = [p.asset for p in s.scalars(select(StyleRefPhoto).where(StyleRefPhoto.style_ref_id == rid)
                                             .order_by(StyleRefPhoto.position)).all()]
    if not assets:
        raise RuntimeError("нет фото-примера")
    trace = Trace(f"[оформление «{name}»]")
    set_note(job_id, "разбор стиля")
    desc, name_ru, cost, prohibited = styleref.describe(st, [storage.get(a) for a in assets], note, trace)
    if prohibited:
        with db.session() as s:
            s.get(StyleRef, rid).status = "draft"
            write_usage(s, org_id, project_id, None, None, trace, f"style:{rid}")
        moderation.record("photo", "фото оформления", "photo", prohibited, "blocked", project_id)
        say("err", f"⛔ Оформление «{name}»: на фото-примере запрещённое содержание ({prohibited[:120]}) — "
                   "оформление не используется. Загрузите другое фото", project_id)
        return
    if not desc:
        raise RuntimeError("ИИ не смог описать стиль — попробуйте другое фото или уточните пожелание")
    with db.session() as s:
        r = s.get(StyleRef, rid)
        r.description = desc
        if name_ru and r.name.startswith("Новое оформление"):
            r.name = name_ru[:120]
        r.status = "ready"
        name = r.name
        write_usage(s, org_id, project_id, None, None, trace, f"style:{rid}")
    say("ok", f"🎨 Оформление «{name}»: стиль разобран · {cost:.2f} ₽", project_id)
