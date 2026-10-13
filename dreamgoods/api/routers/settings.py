"""Настройки проекта, баланс и каталог моделей Polza."""
from fastapi import APIRouter, Body, Depends, Request

from ...ai import polza, prompts
from ...core import admin
from ...core.settings import SECRETS, clean
from ...services import projects
from ..deps import project_id

router = APIRouter(prefix="/api/projects/{project_id}", tags=["настройки"])
# что может менять рядовой пользователь; всё остальное (ключи, модели, провайдеры, лимиты) — только в админ-панели
USER_KEYS = {"qc_enabled", "qc_autoregen"}


@router.patch("/settings")
def update_settings(request: Request, body: dict = Body(...), pid: int = Depends(project_id)):
    """Частичное обновление: передаются только изменённые поля. Ключи сохраняются в организации и не возвращаются."""
    if not admin.is_admin(request) and set(body) - USER_KEYS:
        raise admin.Forbidden("технические настройки меняются в админ-панели")
    secrets = {k: str(body[k]).strip() for k in SECRETS if body.get(k)}
    if body.get("clear_key"):
        secrets["api_key"] = ""
    if body.get("clear_qc_key"):
        secrets["qc_api_key"] = ""
    projects.save_settings(pid, clean(body), secrets)
    polza.balance(projects.project_settings(pid).get("api_key"), force=True)
    return {"ok": True}


@router.get("/settings/defaults")
def defaults():
    return {"qc_checklist": prompts.DEFAULT_CHECKLIST}


@router.get("/balance", dependencies=[Depends(admin.required)])
def balance(pid: int = Depends(project_id)):
    b = polza.balance(projects.project_settings(pid).get("api_key"), force=True)
    return {"balance": b["value"], "error": b["error"]}


@router.get("/catalog")
def catalog(kind: str = "image", refresh: bool = False, pid: int = Depends(project_id)):
    """Модели Polza: kind=image — генерация, kind=qc — модели, которые видят картинки."""
    c = polza.image_models(force=refresh, kind="qc" if kind == "qc" else "image",
                           key=projects.project_settings(pid).get("api_key", ""))
    return {"models": c["models"], "error": c["error"]}
