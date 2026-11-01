"""Референсы оформления: фото-пример стиля + пожелание → разбор ИИ → пример для генератора."""
from fastapi import APIRouter, Depends, Request

from ...core import auth
from ...services import moderation, styles
from ..deps import need_key, project_id
from ..schemas import StyleRefChoice, StyleRefCreate, StyleRefUpdate

router = APIRouter(prefix="/api/projects/{project_id}", tags=["оформление"])


@router.get("/styles")
def listing(pid: int = Depends(project_id)):
    return styles.listing(pid)


@router.post("/styles")
def create(body: StyleRefCreate, request: Request, pid: int = Depends(project_id)):
    moderation.guard("оформление", body.name, body.note, project_id=pid, user=auth.user(request))
    return {"id": styles.create(pid, body.name, body.note, body.blocks)}


@router.patch("/styles/{ref_id}")
def update(ref_id: int, body: StyleRefUpdate, request: Request, pid: int = Depends(project_id)):
    moderation.guard("оформление", body.name, body.note, body.description, project_id=pid, user=auth.user(request))
    styles.update(pid, ref_id, body.model_dump())
    return {"ok": True}


@router.delete("/styles/{ref_id}")
def archive(ref_id: int, pid: int = Depends(project_id)):
    styles.archive(pid, ref_id)
    return {"ok": True}


@router.post("/styles/{ref_id}/photos")
async def upload(ref_id: int, request: Request, name: str = "style.jpg", pid: int = Depends(project_id)):
    return styles.upload_photo(pid, ref_id, await request.body(), name)


@router.delete("/styles/{ref_id}/photos/{photo_id}")
def delete_photo(ref_id: int, photo_id: int, pid: int = Depends(project_id)):
    styles.delete_photo(pid, ref_id, photo_id)
    return {"ok": True}


@router.post("/styles/{ref_id}/describe")
def describe(ref_id: int, pid: int = Depends(project_id)):
    """ИИ разбирает стиль: свет, цвет, фон, композиция, настроение (≈ 0,03 ₽)."""
    need_key(pid)
    styles.describe(pid, ref_id)
    return {"ok": True}


@router.put("/style")
def set_default(body: StyleRefChoice, pid: int = Depends(project_id)):
    styles.set_project_default(pid, body.style_ref_id or 0)
    return {"ok": True}


@router.put("/products/{product_id}/style")
def set_product(product_id: int, body: StyleRefChoice, pid: int = Depends(project_id)):
    styles.set_product(pid, product_id, body.style_ref_id)
    return {"ok": True}
