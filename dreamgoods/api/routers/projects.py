"""Проекты и состояние проекта."""
from fastapi import APIRouter, Depends, Request
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
def state(request: Request, pid: int = Depends(project_id)):
    """Всё, что нужно экрану проекта. Себестоимость, баланс Polza и метрики — только мастеру."""
    return board.state(pid, admin.is_admin(request))
