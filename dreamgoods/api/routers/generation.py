"""Очередь: генерация, проверка, остановка, ошибки."""
from fastapi import APIRouter, Depends, Request

from ...core import admin

from ...core.events import say
from ...services import frames, plans, presets
from ...workers import queue
from ..deps import need_key, project_id
from ..schemas import CheckRequest, Selection

router = APIRouter(prefix="/api/projects/{project_id}", tags=["очередь"])


def _run_options(body: Selection):
    """Пожелания к запуску: текст, площадка и формат поверх пресета (только непустые)."""
    from ...core import presets as P
    out = {}
    if body.brief.strip():
        out["brief"] = body.brief.strip()
    if body.market in P.MARKETS and body.market not in ("none", "custom"):
        out["market"] = body.market
    if body.aspect in P.ASPECTS:
        out["aspect"] = body.aspect
    return out or None


def _to_generate(pid, body: Selection):
    if body.frame_ids is not None:
        return frames.frames_of_project(pid, body.frame_ids)
    return frames.missing_frames(pid, body.product_ids, body.limit)


@router.post("/generate/preview")
def preview_generate(body: Selection, pid: int = Depends(project_id)):
    """Сколько кадров встанет в очередь (для подтверждения и оценки цены) и что изменится по пресету."""
    if body.frame_ids is not None:
        return {"count": len(_to_generate(pid, body)), "preset": None}
    sync = presets.sync_for_generation(pid, body.product_ids, dry_run=True, limit=body.limit)
    return {"count": sync["count"], "preset": sync}


@router.post("/generate")
def generate(body: Selection, pid: int = Depends(project_id)):
    """frame_ids — конкретные кадры (перегенерация); иначе — недостающие кадры выбранных товаров."""
    need_key(pid)
    plans.check_generation_project(pid, body.product_ids if body.frame_ids is None else None)
    sync = presets.sync_for_generation(pid, body.product_ids, limit=body.limit) if body.frame_ids is None else None
    added = frames.enqueue_frames(pid, _to_generate(pid, body), payload=_run_options(body))
    if added:
        say("info", (f"↻ На перегенерацию поставлено кадров: {added}" if body.frame_ids is not None
                     else f"▶ В очередь добавлено кадров: {added}"), pid)
    return {"added": added, "preset": sync}


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


@router.get("/history")
def history(request: Request, before: int | None = None, pid: int = Depends(project_id)):
    """История генераций проекта (вкладка «История»)."""
    return {"items": frames.project_history(pid, admin.is_admin(request), before=before)}
