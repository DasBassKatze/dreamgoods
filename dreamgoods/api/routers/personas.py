"""Модели клиента (люди на кадрах): свои фото или образ, сгенерированный «для примерки»."""
from fastapi import APIRouter, Depends, Request

from ...core import admin
from ...services import personas
from ..deps import need_key, project_id
from ..schemas import PersonaCandidates, PersonaChoice, PersonaCreate, PersonaEdit, PersonaUpdate

router = APIRouter(prefix="/api/projects/{project_id}", tags=["модели клиента"])


@router.get("/personas")
def listing(request: Request, pid: int = Depends(project_id)):
    """Модели клиента этого проекта (общие для всех его проектов) и модель по умолчанию в проекте.
    Паспорт образа (подробное описание внешности и стиля для генератора) — внутренняя кухня: только мастеру."""
    out = personas.listing(pid)
    if not admin.is_admin(request):
        for p in out["personas"]:
            p["description"], p["style"] = "", {}
            for ph in p["photos"]:
                ph.pop("cost", None)
    return out


@router.post("/personas")
def create(body: PersonaCreate, pid: int = Depends(project_id)):
    return {"id": personas.create(pid, body.name, body.brief, body.source)}


@router.patch("/personas/{persona_id}")
def update(persona_id: int, body: PersonaUpdate, request: Request, pid: int = Depends(project_id)):
    values = body.model_dump()
    if not admin.is_admin(request):          # паспорт меняет только мастер
        values.pop("description", None)
        values.pop("style", None)
    personas.update(pid, persona_id, values)
    return {"ok": True}


@router.delete("/personas/{persona_id}")
def archive(persona_id: int, pid: int = Depends(project_id)):
    personas.archive(pid, persona_id)
    return {"ok": True}


@router.post("/personas/{persona_id}/photos")
async def upload(persona_id: int, request: Request, name: str = "model.jpg", pid: int = Depends(project_id)):
    """Тело запроса — байты фото модели (нужно согласие человека: consent=true у модели)."""
    return personas.upload_photo(pid, persona_id, await request.body(), name)


@router.delete("/personas/{persona_id}/photos/{photo_id}")
def delete_photo(persona_id: int, photo_id: int, pid: int = Depends(project_id)):
    personas.delete_photo(pid, persona_id, photo_id)
    return {"ok": True}


@router.post("/personas/{persona_id}/describe")
def describe(persona_id: int, pid: int = Depends(project_id)):
    """ИИ описывает внешность по фото — это описание идёт в промпты кадров."""
    need_key(pid)
    personas.describe(pid, persona_id)
    return {"ok": True}


@router.post("/personas/{persona_id}/candidates")
def candidates(persona_id: int, body: PersonaCandidates, pid: int = Depends(project_id)):
    """Сгенерировать варианты образа по пожеланиям (1–4 картинки, каждая — одна генерация)."""
    need_key(pid)
    personas.generate_candidates(pid, persona_id, body.count, body.brief)
    return {"ok": True}


@router.post("/personas/{persona_id}/edit")
def edit(persona_id: int, body: PersonaEdit, pid: int = Depends(project_id)):
    """Изменить внешность выбранной модели: ИИ правит паспорт образа, генератор меняет основное фото (1–4 варианта)."""
    need_key(pid)
    personas.edit(pid, persona_id, body.request, body.count)
    return {"ok": True}


@router.post("/personas/{persona_id}/choose")
def choose(persona_id: int, body: PersonaChoice, pid: int = Depends(project_id)):
    personas.choose(pid, persona_id, body.photo_id)
    return {"ok": True}


@router.post("/personas/{persona_id}/sheet")
def sheet(persona_id: int, pid: int = Depends(project_id)):
    """Дополнительные ракурсы выбранного образа (портрет, ¾, профиль) — 3 генерации."""
    need_key(pid)
    personas.make_sheet(pid, persona_id)
    return {"ok": True}


@router.put("/persona")
def set_default(body: PersonaChoice, pid: int = Depends(project_id)):
    """Модель по умолчанию для проекта; persona_id=0 — без модели клиента."""
    personas.set_project_default(pid, body.persona_id or 0)
    return {"ok": True}


@router.put("/products/{product_id}/persona")
def set_product(product_id: int, body: PersonaChoice, pid: int = Depends(project_id)):
    """Своя модель для товара; persona_id=null — как в проекте."""
    personas.set_product_persona(pid, product_id, body.persona_id)
    return {"ok": True}
