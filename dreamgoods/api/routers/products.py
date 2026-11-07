"""Товар: референсы и профиль."""
from fastapi import APIRouter, Depends, Request

from ...core.events import say
from ...core import auth
from ...services import moderation, products
from ..deps import need_key, project_id
from ..schemas import ProfileGenerate, ProfileUpdate, RefsUpdate

router = APIRouter(prefix="/api/projects/{project_id}", tags=["товары"])


@router.put("/products/{product_id}/refs")
def set_refs(product_id: int, body: RefsUpdate, pid: int = Depends(project_id)):
    return {"selected": products.set_refs(pid, product_id, body.selected)}


@router.get("/products/{product_id}/profile")
def get_profile(product_id: int, pid: int = Depends(project_id)):
    return products.get_profile(pid, product_id)


@router.put("/products/{product_id}/profile")
def save_profile(product_id: int, body: ProfileUpdate, request: Request, pid: int = Depends(project_id)):
    moderation.guard("профиль товара", {k: v for k, v in (body.profile or {}).items() if k != "prohibited"},
                     project_id=pid, product_id=product_id, user=auth.user(request))
    return {"ok": True, "prompts": products.save_profile(pid, product_id, body.profile, body.build)}


@router.post("/profiles/generate")
def generate_profiles(body: ProfileGenerate, pid: int = Depends(project_id)):
    """ИИ составит профиль товара по фото; build — сразу собрать промпты кадров. product_ids=None — все без промптов."""
    need_key(pid)
    added = products.profile_jobs(pid, body.product_ids, body.build)
    if added:
        say("info", f"🧠 Составляю профили товара по фото: {added}", pid)
    return {"added": added}


@router.post("/products/delete")
def delete_products(body: dict, pid: int = Depends(project_id)):
    ids = body.get("product_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 1000 or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("передайте от 1 до 1000 выбранных товаров")
    return products.delete_products(pid, ids)
