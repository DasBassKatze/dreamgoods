"""Задание «subcats»: ИИ определяет подразделы (Сапоги, Ботинки…) у товаров, чьи профили составлены раньше.
Один текстовый запрос на пачку до 80 товаров, без картинок — копейки."""
from sqlalchemy import select

from .. import db
from ..ai import prompts
from ..core.events import say
from ..core.logs import Trace
from ..db.models import Job, Product, ProductProfile
from ..services.common import context, write_usage
from .queue import set_note


def handle(job_id):
    with db.session() as s:
        job = s.get(Job, job_id)
        project_id = job.project_id
        rows = s.execute(select(Product, ProductProfile).join(ProductProfile, ProductProfile.id == Product.current_profile_id)
                         .where(Product.project_id == project_id)).all()
        todo = [(p.id, pp.id, (pp.data or {})) for p, pp in rows if not (pp.data or {}).get("subcategory_ru")]
        if not todo:
            return
        _, org, st = context(s, rows[0][0])
        org_id = org.id
    trace = Trace("[подразделы]")
    found = {}
    for i in range(0, len(todo), 80):
        chunk = todo[i:i + 80]
        set_note(job_id, f"подразделы {i + len(chunk)}/{len(todo)}")
        items = [{"id": pid, "category": d.get("category_ru") or "", "summary": d.get("summary_ru") or d.get("object") or ""}
                 for pid, _, d in chunk]
        res, _ = prompts.subcategories(st, items, trace)
        found.update(res)
    with db.session() as s:
        for pid, ppid, _ in todo:
            if pid in found:
                pp = s.get(ProductProfile, ppid)
                pp.data = {**(pp.data or {}), "subcategory_ru": found[pid]}
        write_usage(s, org_id, project_id, None, None, trace, "subcats")
    say("ok", f"🗂 Подразделы определены у товаров: {len(found)} из {len(todo)}", project_id)
