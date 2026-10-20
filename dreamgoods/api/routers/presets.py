"""Пресеты генерации: уровень качества + план кадров по блокам; применение к товарам и категориям."""
from fastapi import APIRouter, Depends, Request

from ...core import admin, auth

from ...services import moderation, presets
from ..deps import need_key, project_id
from ..schemas import PresetApply, PresetSave

router = APIRouter(prefix="/api/projects/{project_id}/presets", tags=["пресеты генерации"])


@router.get("")
def listing(request: Request, pid: int = Depends(project_id)):
    """Пресеты организации, пресет проекта, уровни качества, блоки кадров и категории товаров проекта.
    Статистика моделей по кадрам (цена, % прохождения) — только администратору."""
    out = presets.listing(pid)
    if not admin.is_admin(request):
        out["model_stats"] = []
    return out


@router.post("/subcategories")
def subcategories(pid: int = Depends(project_id)):
    """ИИ определит подразделы (Сапоги, Ботинки…) у товаров, где их ещё нет. Один текстовый запрос на 80 товаров."""
    need_key(pid)
    presets.detect_subcategories(pid)
    return {"ok": True}


def _guard(body, request, pid):
    d = body.model_dump()
    moderation.guard("пресет", d.get("name"), d.get("description"), d.get("manual"), (d.get("market") or {}).get("cover_extra"),
                     (d.get("market") or {}).get("cover_bg"), project_id=pid, user=auth.user(request))


@router.post("")
def create(body: PresetSave, request: Request, pid: int = Depends(project_id)):
    _guard(body, request, pid)
    return {"id": presets.save(pid, None, body.model_dump(), admin.is_admin(request))}


@router.put("/{preset_id}")
def update(preset_id: int, body: PresetSave, request: Request, pid: int = Depends(project_id)):
    _guard(body, request, pid)
    presets.save(pid, preset_id, body.model_dump(), admin.is_admin(request))
    return {"ok": True}


@router.delete("/{preset_id}")
def archive(preset_id: int, request: Request, pid: int = Depends(project_id)):
    presets.archive(pid, preset_id, admin.is_admin(request))
    return {"ok": True}


@router.post("/{preset_id}/apply")
def apply(preset_id: int, body: PresetApply, pid: int = Depends(project_id)):
    """preset_id=0 — снять пресет (товары вернутся к пресету проекта). dry_run=true — только посчитать."""
    return presets.apply(pid, preset_id or None, body.product_ids, body.categories, body.everything, body.make_default,
                         body.rebuild, body.dry_run)
