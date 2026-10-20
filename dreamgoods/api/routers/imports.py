"""Импорт фото: загрузка кучей или папками → ИИ раскладывает по товарам → подтверждение."""
from fastapi import APIRouter, Depends, Request

from ...core import auth
from ...services import importer, moderation, plans
from ..deps import need_key, project_id
from ..schemas import ImportAnalyze, ImportApply

router = APIRouter(prefix="/api/projects/{project_id}/imports", tags=["импорт"])


def session_id(import_id: int, pid: int = Depends(project_id)) -> int:
    importer.get_session(import_id, pid)
    return import_id


@router.post("")
def new_import(pid: int = Depends(project_id)):
    plans.check_storage_project(pid)
    return {"id": importer.new_session(pid)}


@router.get("/{import_id}")
def get_import(sid: int = Depends(session_id)):
    return importer.view(sid)


@router.post("/{import_id}/files")
async def upload(request: Request, path: str = "file.jpg", sid: int = Depends(session_id)):
    """Тело запроса — байты файла (фото); path — относительный путь (папка/имя), из него берётся группа."""
    added, total = importer.upload(sid, path, await request.body())
    return {"added": added, "total": total}


@router.post("/{import_id}/analyze")
def analyze(body: ImportAnalyze, request: Request, sid: int = Depends(session_id), pid: int = Depends(project_id)):
    need_key(pid)
    moderation.guard("правило раскладки", body.sort_rule, project_id=pid, user=auth.user(request))
    importer.analyze_request(sid, body.group_mode, body.label_mode, body.sort_rule)
    return {"ok": True}


@router.post("/{import_id}/apply")
def apply(body: ImportApply, request: Request, sid: int = Depends(session_id), pid: int = Depends(project_id)):
    moderation.guard("описание товара", [g.description for g in body.groups], project_id=pid, user=auth.user(request))
    return importer.apply_request(sid, [g.model_dump() for g in body.groups], body.label_mode, body.auto_profile)
