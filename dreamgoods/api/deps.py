"""Общие зависимости маршрутов: текущий пользователь, проект из пути с проверкой доступа, ключ и баланс."""
from fastapi import Path, Request

from .. import db
from ..core.auth import Forbidden, user
from ..db.models import Project
from ..services import billing, projects


def project_id(request: Request, project_id: int = Path(..., description="ID проекта")) -> int:
    """Проект из пути /api/projects/{project_id}/…: 404, если его нет; 403 — если он чужой.
    Пользователь видит только проекты своего клиента, мастер — все."""
    u = user(request)
    with db.session() as s:
        p = s.get(Project, project_id)
        if not p or p.archived:
            raise LookupError("проект не найден")
        if not u.master and p.client_id != u.client_id:
            raise Forbidden("нет доступа к этому проекту")
        return p.id


def need_key(pid: int):
    """Перед платным заданием: есть ключ Polza и деньги на балансе клиента."""
    if not projects.project_settings(pid).get("api_key"):
        raise ValueError("Не настроен ключ Polza — обратитесь к администратору сервиса")
    billing.ensure_funds(pid)
