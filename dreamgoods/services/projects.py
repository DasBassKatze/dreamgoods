"""Организация, клиенты, проекты и их настройки."""
from sqlalchemy import func, select

from .. import db
from ..ai import prompts
from ..core.logs import log
from ..core.settings import effective
from ..db.models import CategoryChecklist, Client, Organization, Project, User


def bootstrap():
    """Первый запуск: библиотека чек-листов, организация, клиент и проект по умолчанию."""
    with db.session() as s:
        if not s.scalar(select(func.count(CategoryChecklist.id)).where(CategoryChecklist.org_id.is_(None))):
            for k, v in prompts.DEFAULT_LIBRARY.items():
                s.add(CategoryChecklist(org_id=None, key=k, name=v["name"], checklist=v["checklist"]))
            log.info("База: заполнена библиотека чек-листов категорий (%d)", len(prompts.DEFAULT_LIBRARY))
        org = s.scalars(select(Organization).order_by(Organization.id)).first()
        if not org:
            org = Organization(name="Моё агентство", settings={})
            s.add(org)
            s.flush()
            s.add(User(org_id=org.id, email="admin", name="Мастер", role="master"))
            log.info("База: создана организация «%s»", org.name)
        client = s.scalars(select(Client).where(Client.org_id == org.id).order_by(Client.id)).first()
        if not client:
            client = Client(org_id=org.id, name="Мой магазин")
            s.add(client)
            s.flush()
        if not s.scalar(select(Project.id).where(Project.client_id == client.id)):
            s.add(Project(client_id=client.id, name="Основной проект", settings={}))
        return org.id


def org_of(s):
    """Текущая организация (пока одна на установку; с авторизацией — из пользователя)."""
    return s.scalars(select(Organization).order_by(Organization.id)).first()


def projects(user=None):
    """Проекты пользователя: мастер видит все, пользователь — только своего клиента.
    С каждым: товаров, готовых кадров и картинка для списка (последний готовый кадр или первое фото товара)."""
    from ..db.models import Frame, Generation, Product, ProductPhoto
    with db.session() as s:
        q = (select(Project, Client).join(Client, Client.id == Project.client_id)
             .where(Project.archived.is_(False)).order_by(Client.name, Project.name))
        if user is not None and not user.master:
            q = q.where(Project.client_id == (user.client_id or 0))
        rows = s.execute(q).all()
        ids = [p.id for p, _ in rows]
        counts = dict(s.execute(select(Product.project_id, func.count(Product.id)).where(Product.project_id.in_(ids))
                                .group_by(Product.project_id)).all()) if ids else {}
        thumbs = {}
        if ids:
            for pid, asset in s.execute(select(Product.project_id, Generation.output_asset_id)
                                        .join(Frame, Frame.product_id == Product.id)
                                        .join(Generation, Generation.id == Frame.current_generation_id)
                                        .where(Product.project_id.in_(ids)).order_by(Generation.id)).all():
                thumbs[pid] = asset                       # последний готовый кадр
            for pid, asset in s.execute(select(Product.project_id, ProductPhoto.asset_id)
                                        .join(ProductPhoto, ProductPhoto.product_id == Product.id)
                                        .where(Product.project_id.in_(ids), ProductPhoto.role != "label")
                                        .order_by(ProductPhoto.id.desc())).all():
                thumbs.setdefault(pid, asset)             # нет кадров — фото товара
        return [{"id": p.id, "name": p.name, "client": c.name, "client_id": c.id, "products": counts.get(p.id, 0),
                 "thumb": str(thumbs[p.id]) if p.id in thumbs else None} for p, c in rows]


_storage_cache = {}


def storage_usage(user):
    """Сколько места занимают файлы кабинета (фото товаров, кадры, модели, оформление, импорт). Мастер — всего сервиса.
    Квота: своя у кабинета (настройка мастера) или общая из настроек организации."""
    import time
    from sqlalchemy import union
    from ..db.models import (Asset, Frame, Generation, ImportFile, ImportSession, Persona, PersonaPhoto, Product,
                             ProductPhoto, StyleRef, StyleRefPhoto)
    key = ("all" if user.master else user.client_id)
    hit = _storage_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    with db.session() as s:
        org = s.get(Organization, user.org_id)
        default_gb = float((org.settings or {}).get("storage_quota_gb") or 10)
        if user.master:
            used = s.scalar(select(func.coalesce(func.sum(Asset.bytes), 0)).where(Asset.org_id == user.org_id)) or 0
            quota_gb = float((org.settings or {}).get("storage_total_gb") or 100)
        else:
            cid = user.client_id or 0
            parts = union(
                select(ProductPhoto.asset_id.label("a")).join(Product, Product.id == ProductPhoto.product_id)
                .join(Project, Project.id == Product.project_id).where(Project.client_id == cid),
                select(Generation.output_asset_id.label("a")).join(Frame, Frame.id == Generation.frame_id)
                .join(Product, Product.id == Frame.product_id).join(Project, Project.id == Product.project_id)
                .where(Project.client_id == cid, Generation.output_asset_id.is_not(None)),
                select(PersonaPhoto.asset_id.label("a")).join(Persona, Persona.id == PersonaPhoto.persona_id)
                .where(Persona.client_id == cid),
                select(StyleRefPhoto.asset_id.label("a")).join(StyleRef, StyleRef.id == StyleRefPhoto.style_ref_id)
                .where(StyleRef.client_id == cid),
                select(ImportFile.asset_id.label("a")).join(ImportSession, ImportSession.id == ImportFile.session_id)
                .join(Project, Project.id == ImportSession.project_id).where(Project.client_id == cid),
            ).subquery()
            used = s.scalar(select(func.coalesce(func.sum(Asset.bytes), 0)).where(Asset.id.in_(select(parts.c.a)))) or 0
            c = s.get(Client, cid)
            quota_gb = float(getattr(c, "storage_quota_gb", None) or default_gb) if c else default_gb
    out = {"used": int(used), "quota": int(quota_gb * 1024 ** 3)}
    _storage_cache[key] = (time.time() + 60, out)
    return out


def rename_project(project_id, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("укажите название")
    with db.session() as s:
        p = s.get(Project, project_id)
        if s.scalar(select(Project.id).where(Project.client_id == p.client_id, Project.name == name, Project.id != p.id)):
            raise ValueError(f"проект «{name}» уже есть")
        p.name = name[:200]


def archive_project(project_id):
    with db.session() as s:
        p = s.get(Project, project_id)
        if s.scalar(select(func.count(Project.id)).where(Project.client_id == p.client_id, Project.archived.is_(False))) <= 1:
            raise ValueError("нельзя убрать единственный проект")
        p.archived = True


def default_project():
    with db.session() as s:
        p = s.scalars(select(Project).where(Project.archived.is_(False)).order_by(Project.id)).first()
        if not p:
            raise LookupError("нет проектов")
        return p.id


def ensure_project(project_id):
    with db.session() as s:
        p = s.get(Project, project_id)
        if not p or p.archived:
            raise LookupError("проект не найден")
        return p.id


def create_project(client_name, name, user=None):
    """Пользователь создаёт проект только у своего клиента; мастер — у любого (по имени клиента)."""
    with db.session() as s:
        org = org_of(s)
        if user is not None and not user.master:
            c = s.get(Client, user.client_id or 0)
            if not c:
                raise ValueError("у вашей учётной записи нет кабинета — обратитесь к администратору")
        elif not (client_name or "").strip() and user is not None and user.client_id:
            c = s.get(Client, user.client_id)        # мастер без указания кабинета — в свой
        else:
            c = s.scalar(select(Client).where(Client.org_id == org.id, Client.name == client_name.strip()))
        if not c:
            c = Client(org_id=org.id, name=client_name.strip() or "Клиент")
            s.add(c)
            s.flush()
        pname = name.strip() or "Новый проект"
        if s.scalar(select(Project.id).where(Project.client_id == c.id, Project.name == pname)):
            raise ValueError(f"У клиента «{c.name}» уже есть проект «{pname}» — выберите другое название")
        p = Project(client_id=c.id, name=pname, settings={})
        s.add(p)
        s.flush()
        log.info("Создан проект «%s» клиента «%s»", p.name, c.name)
        return p.id


def project_settings(project_id):
    """Действующие настройки проекта (с ключами — только для серверного кода)."""
    with db.session() as s:
        p = s.get(Project, project_id)
        org = s.get(Organization, p.client.org_id)
        return effective(org, p)


def save_settings(project_id, values, secrets):
    """values — настройки проекта; secrets — ключи (в настройки организации, наружу не отдаются)."""
    with db.session() as s:
        p = s.get(Project, project_id)
        org = s.get(Organization, p.client.org_id)
        before = effective(org, p)
        p.settings = {**(p.settings or {}), **values}
        if secrets:
            org.settings = {**(org.settings or {}), **secrets}
        after = effective(org, p)
    changed = [k for k in values if before.get(k) != after.get(k)] + [k for k in secrets]
    if changed:
        log.info("⚙ Проект %s: изменены настройки %s", project_id, ", ".join(
            f"{k}=***" if "key" in k else f"{k}=…" if k == "qc_checklist" else f"{k}={after.get(k)}" for k in changed))
