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
    """Проекты пользователя: мастер видит все, пользователь — только своего клиента."""
    with db.session() as s:
        q = (select(Project, Client).join(Client, Client.id == Project.client_id)
             .where(Project.archived.is_(False)).order_by(Client.name, Project.name))
        if user is not None and not user.master:
            q = q.where(Project.client_id == (user.client_id or 0))
        rows = s.execute(q).all()
        return [{"id": p.id, "name": p.name, "client": c.name, "client_id": c.id} for p, c in rows]


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
