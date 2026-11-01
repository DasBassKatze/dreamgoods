"""Очередь: генерация, проверка, остановка, ошибки."""
from fastapi import APIRouter, Depends

from ...core.events import say
from ...services import frames, estimates
from ...workers import queue
from ..deps import need_key, project_id
from ..schemas import CheckRequest, Selection

router = APIRouter(prefix="/api/projects/{project_id}", tags=["очередь"])


def _to_generate(pid, body: Selection):
    if body.frame_ids is not None:
        return frames.frames_of_project(pid, body.frame_ids)
    return frames.missing_frames(pid, body.product_ids, body.limit)


@router.post("/generate/preview")
def preview_generate(body: Selection, pid: int = Depends(project_id)):
    """Сколько кадров встанет в очередь (для подтверждения и оценки цены)."""
    return estimates.preview(pid, _to_generate(pid, body))


@router.post("/generate")
def generate(body: Selection, pid: int = Depends(project_id)):
    """frame_ids — конкретные кадры (перегенерация); иначе — недостающие кадры выбранных товаров."""
    need_key(pid)
    added = frames.enqueue_frames(pid, _to_generate(pid, body), budget_rub=body.budget_rub, retry_budget_rub=body.retry_budget_rub)
    if added:
        say("info", (f"↻ На перегенерацию поставлено кадров: {added}" if body.frame_ids is not None
                     else f"▶ В очередь добавлено кадров: {added}"), pid)
    return {"added": added}


@router.post("/check/preview")
def preview_check(body: CheckRequest, pid: int = Depends(project_id)):
    return {"count": len(frames.checkable_frames(pid, body.product_ids, body.frame_ids, body.only_unchecked))}


@router.post("/check")
def check(body: CheckRequest, pid: int = Depends(project_id)):
    need_key(pid)
    added = frames.enqueue_frames(pid, frames.checkable_frames(pid, body.product_ids, body.frame_ids, body.only_unchecked),
                                  kind="check")
    if added:
        say("info", f"🔍 На проверку поставлено кадров: {added}", pid)
    return {"added": added}


@router.post("/stop")
def stop(pid: int = Depends(project_id)):
    return {"cancelled": queue.stop(pid)}


@router.post("/errors/clear")
def clear_errors(pid: int = Depends(project_id)):
    frames.clear_errors(pid)
    return {"ok": True}

