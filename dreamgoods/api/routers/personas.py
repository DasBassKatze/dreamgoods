"""Модели клиента (люди на кадрах): свои фото или образ, сгенерированный «для примерки»."""
from fastapi import APIRouter, Depends, Request

from ...core import admin, auth
from ...services import moderation, personas
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
def create(body: PersonaCreate, request: Request, pid: int = Depends(project_id)):
    moderation.guard("описание модели", body.name, body.brief, project_id=pid, user=auth.user(request))
    return {"id": personas.create(pid, body.name, body.brief, body.source)}


@router.patch("/personas/{persona_id}")
def update(persona_id: int, body: PersonaUpdate, request: Request, pid: int = Depends(project_id)):
    values = body.model_dump()
    moderation.guard("описание модели", values.get("name"), values.get("brief"), values.get("description"),
                     values.get("style"), project_id=pid, user=auth.user(request))
    if not admin.is_admin(request):          # паспорт меняет только мастер
        values.pop("description", None)
        values.pop("style", None)
    was = personas.consent_of(pid, persona_id) if values.get("consent") is not None else None
    personas.update(pid, persona_id, values)
    if values.get("consent") is not None and bool(values["consent"]) != was:
        # подтверждение (или снятие) согласия человека на фото — в журнал согласий: кто, когда, откуда
        personas.record_consent(pid, persona_id, auth.user(request), bool(values["consent"]),
                                request.client.host if request.client else "", request.headers.get("user-agent", ""))
    return {"ok": True}


@router.delete("/personas/{persona_id}")
def archive(persona_id: int, pid: int = Depends(project_id)):
    personas.archive(pid, persona_id)
    return {"ok": True}


@router.post("/personas/{persona_id}/photos")
async def upload(persona_id: int, request: Request, name: str = "model.jpg", pid: int = Depends(project_id)):
    """Тело запроса — байты фото модели (нужно согласие человека: consent=true у модели)."""
    return personas.upload_photo(pid, persona_id, await request.body(), name)


@router.post("/personas/{persona_id}/refs")
async def upload_ref(persona_id: int, request: Request, name: str = "ref.jpg", pid: int = Depends(project_id)):
    """Референс образа (пример стиля для генерации модели). Тело запроса — байты картинки."""
    return personas.upload_ref(pid, persona_id, await request.body(), name)


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
def candidates(persona_id: int, body: PersonaCandidates, request: Request, pid: int = Depends(project_id)):
    moderation.guard("образ модели", body.brief, project_id=pid, user=auth.user(request))
    """Сгенерировать варианты образа по пожеланиям (1–4 картинки, каждая — одна генерация)."""
    need_key(pid)
    personas.generate_candidates(pid, persona_id, body.count, body.brief)
    return {"ok": True}


@router.post("/personas/{persona_id}/edit")
def edit(persona_id: int, body: PersonaEdit, request: Request, pid: int = Depends(project_id)):
    moderation.guard("правка модели", body.request, project_id=pid, user=auth.user(request))
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
