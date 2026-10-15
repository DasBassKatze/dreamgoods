"""Кадр: правка по промпту, версии, ручное решение (промпт кадра — только для админа)."""
from fastapi import APIRouter, Depends, Request

from ...core import admin
from ...services import frames
from ..deps import need_key, project_id
from ..schemas import EditRequest, PromptUpdate, QuickAction, RestoreRequest, ReviewRequest

router = APIRouter(prefix="/api/projects/{project_id}/frames/{frame_id}", tags=["кадры"])


@router.get("/prompt", dependencies=[Depends(admin.required)])
def get_prompt(frame_id: int, pid: int = Depends(project_id)):
    return {"prompt": frames.get_prompt(pid, frame_id)}


@router.put("/prompt", dependencies=[Depends(admin.required)])
def set_prompt(frame_id: int, body: PromptUpdate, pid: int = Depends(project_id)):
    frames.set_prompt(pid, frame_id, body.text)
    return {"ok": True}


@router.post("/edit")
def edit(frame_id: int, body: EditRequest, pid: int = Depends(project_id)):
    """Правка готового фото: «что изменить» → новая версия кадра (прежняя остаётся в истории)."""
    need_key(pid)
    frames.edit(pid, frame_id, body.instruction, body.source_id)
    return {"ok": True}


@router.post("/quick")
def quick(frame_id: int, body: QuickAction, pid: int = Depends(project_id)):
    """Улучшить до 4K / убрать фон — правка готового кадра готовой инструкцией."""
    need_key(pid)
    frames.quick(pid, frame_id, body.action)
    return {"ok": True}


@router.get("/history")
def history(frame_id: int, request: Request, pid: int = Depends(project_id)):
    return {"versions": frames.history(pid, frame_id, admin.is_admin(request))}


@router.post("/restore")
def restore(frame_id: int, body: RestoreRequest, pid: int = Depends(project_id)):
    frames.restore(pid, frame_id, body.generation_id)
    return {"ok": True}


@router.post("/review")
def review(frame_id: int, body: ReviewRequest, pid: int = Depends(project_id)):
    """Принять / брак / брак и переделать (замечание уходит в промпт и в чек-лист проверки товара)."""
    frames.review(pid, frame_id, body.verdict, body.comment.strip(), body.regen)
    return {"ok": True}
