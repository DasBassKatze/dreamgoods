"""Действия с товарами: выбор референсов, профиль товара (просмотр, правка, составление ИИ)."""
from sqlalchemy import func, select

from .. import db
from ..ai import prompts
from ..core.events import say
from ..core.logs import log
from ..db.models import Frame, Product, ProductPhoto, ProductProfile, Project
from ..workers.queue import enqueue
from .common import library, product_in, rebuild_frames


def set_refs(project_id, product_id, selected):
    """selected — id файлов (asset) фото, которые идут в генерацию."""
    with db.session() as s:
        p = product_in(s, project_id, product_id)
        sel = set(map(str, selected))
        n = 0
        for ph in s.scalars(select(ProductPhoto).where(ProductPhoto.product_id == p.id, ProductPhoto.role != "label")).all():
            ph.is_reference = str(ph.asset_id) in sel
            n += ph.is_reference
        sku = p.sku
    log.info("[%s] референсы: выбрано %d", sku, n)
    return n


def get_profile(project_id, product_id):
    with db.session() as s:
        p = product_in(s, project_id, product_id)
        org_id = s.get(Project, project_id).client.org_id
        pp = s.get(ProductProfile, p.current_profile_id) if p.current_profile_id else None
        n = s.scalar(select(func.count(Frame.id)).where(Frame.product_id == p.id, Frame.status != "retired"))
        meta = None
        if pp:
            meta = {"model": pp.model, "created_at": pp.created_at.strftime("%Y-%m-%d %H:%M"), "version": pp.version,
                    "source": pp.source}
        return {"sku": p.sku, "profile": dict(pp.data) if pp else None, "meta": meta, "prompts": n,
                "categories": [{"key": k, "name": v.get("name", k)} for k, v in library(s, org_id).items()]}


def save_profile(project_id, product_id, data, build):
    """Новая версия профиля из правок; build — пересобрать промпты кадров."""
    with db.session() as s:
        p = product_in(s, project_id, product_id)
        org_id = s.get(Project, project_id).client.org_id
        prof = dict(s.get(ProductProfile, p.current_profile_id).data if p.current_profile_id else {})
        for k in prompts.PROFILE_TEXT:
            if k in data:
                prof[k] = str(data[k] or "").strip()
        for k in prompts.PROFILE_LISTS:
            if k in data:
                v = data[k]
                prof[k] = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else prompts._lines(v)
        for k in ("category", "is_pair"):
            if k in data:
                prof[k] = bool(data[k]) if k == "is_pair" else str(data[k])
        lib = library(s, org_id)
        if prof.get("category") in lib:
            prof["category_ru"] = lib[prof["category"]].get("name", prof["category"])
        last = s.scalar(select(func.max(ProductProfile.version)).where(ProductProfile.product_id == p.id)) or 0
        pp = ProductProfile(product_id=p.id, version=last + 1, data=prof, source="manual")
        s.add(pp)
        s.flush()
        p.current_profile_id, p.category = pp.id, prof.get("category") or p.category
        n = rebuild_frames(s, p, prof) if build else 0
        sku = p.sku
    log.info("[%s] профиль изменён вручную (версия %d)%s", sku, last + 1, f", промптов кадров: {n}" if build else "")
    if build:
        say("ok", f"✨ {sku}: промпты пересобраны из профиля — {n}", project_id)
    return n


def profile_jobs(project_id, product_ids, build):
    """Ставит составление профиля ИИ. product_ids=None — все товары без кадров."""
    with db.session() as s:
        products = s.scalars(select(Product).where(Product.project_id == project_id)).all()
        if product_ids is None:
            have = set(s.scalars(select(Frame.product_id).where(Frame.product_id.in_([p.id for p in products]))).all())
            products = [p for p in products if p.id not in have]
        else:
            want = set(map(int, product_ids))
            products = [p for p in products if p.id in want]
        n = 0
        for p in products:
            if enqueue(s, "profile", project_id, product_id=p.id, payload={"build": bool(build)}, priority=20):
                n += 1
    return n


def delete_products(project_id, product_ids):
    """Delete only an explicit selection; keep financial ledger and refuse in-flight work."""
    from sqlalchemy import delete, or_
    from ..db.models import Generation, Job, PaidOperation
    from ..workers.queue import ACTIVE
    from .payments import HELD
    ids = list(dict.fromkeys(int(i) for i in (product_ids or [])))
    if not ids:
        raise ValueError("выберите товары для удаления")
    with db.session() as s:
        rows = s.scalars(select(Product).where(Product.project_id == project_id, Product.id.in_(ids))
                         .order_by(Product.id).with_for_update()).all()
        if len(rows) != len(ids):
            raise LookupError("товар не найден в проекте")
        frames = s.scalars(select(Frame).where(Frame.product_id.in_(ids)).order_by(Frame.id).with_for_update()).all()
        fids = [f.id for f in frames]
        jobs = s.scalars(select(Job).where(or_(Job.product_id.in_(ids), Job.frame_id.in_(fids)))
                         .order_by(Job.id).with_for_update()).all()
        if any(j.status in ACTIVE for j in jobs):
            raise ValueError("у товара есть активные задания — остановите их и дождитесь завершения")
        if s.scalar(select(Generation.id).where(Generation.frame_id.in_(fids), Generation.status == "pending").limit(1)):
            raise ValueError("ожидается оплаченный результат — дождитесь его получения перед удалением")
        if s.scalar(select(PaidOperation.id).where(PaidOperation.product_id.in_(ids), PaidOperation.status.in_(HELD)).limit(1)):
            raise ValueError("есть незавершённые платные операции — сначала выполните сверку в бюджетах")
        s.execute(delete(Product).where(Product.project_id == project_id, Product.id.in_(ids)))
    say("info", f"Удалено товаров: {len(ids)}", project_id)
    from .projects import _storage_cache
    _storage_cache.clear()
    return {"deleted": len(ids), "ids": ids}
