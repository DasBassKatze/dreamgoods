"""Проекты и состояние проекта."""
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from ...core import admin, auth
from ...services import board, projects
from ..deps import project_id
from ..schemas import ProjectCreate

router = APIRouter(prefix="/api/projects", tags=["проекты"])


class ProjectRename(BaseModel):
    name: str


@router.get("")
def list_projects(request: Request):
    return {"projects": projects.projects(auth.user(request))}


@router.post("")
def create_project(body: ProjectCreate, request: Request):
    return {"id": projects.create_project(body.client, body.name, auth.user(request))}


@router.patch("/{project_id}")
def rename(body: ProjectRename, pid: int = Depends(project_id)):
    projects.rename_project(pid, body.name)
    return {"ok": True}


@router.delete("/{project_id}")
def archive(pid: int = Depends(project_id)):
    projects.archive_project(pid)
    return {"ok": True}


@router.get("/{project_id}/state")
def state(request: Request, pid: int = Depends(project_id), page: int = Query(1, ge=1),
          page_size: int = Query(40, ge=1, le=100), query: str = "", status: str = "all"):
    """Всё, что нужно экрану проекта. Себестоимость, баланс Polza и метрики — только мастеру."""
    return board.state(pid, admin.is_admin(request), page, page_size, query, status)



@router.get("/{project_id}/progress")
def progress(pid: int = Depends(project_id)):
    return board.progress(pid)


@router.get("/{project_id}/events")
async def events(request: Request, pid: int = Depends(project_id)):
    import asyncio
    import json
    token = auth.token_of(request)
    async def stream():
        previous = None
        while not await request.is_disconnected():
            current_user = await run_in_threadpool(auth.user_by_token, token)
            if current_user is None:
                break
            # Access can be revoked while the stream is open.
            try:
                await run_in_threadpool(projects.require_project, pid, current_user)
            except (LookupError, PermissionError):
                break
            data = await run_in_threadpool(board.progress, pid)
            if data["version"] != previous:
                previous = data["version"]
                yield "data: " + json.dumps(data) + "\n\n"
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(3)
    return StreamingResponse(stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
