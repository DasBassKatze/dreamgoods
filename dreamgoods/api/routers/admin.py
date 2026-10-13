"""Мастер-панель: пользователи, ключи Polza, финансы, метрики и расходы, очередь, журнал сервера."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel

from ...core import auth
from ...services import admin as svc
from ...services import billing, users
from ...workers import queue, resume
from ..deps import project_id
from ..schemas import ParallelUpdate

router = APIRouter(prefix="/api/admin", tags=["мастер"], dependencies=[Depends(auth.master)])


class TopUp(BaseModel):
    amount: float
    note: str = ""


@router.get("/projects/{project_id}/overview")
def overview(pid: int = Depends(project_id)):
    return svc.overview(pid)


@router.get("/log")
def log_tail(lines: int = 300, level: str = ""):
    return {"lines": svc.log_tail(lines, level)}


@router.put("/parallel")
def parallel(body: ParallelUpdate):
    return {"parallel": queue.set_parallel(body.n)}


@router.post("/resume")
def resume_now():
    """Сразу проверить задачи Polza, результат которых не был получен (обрыв связи, перезапуск)."""
    return {"resumed": resume.run_once()}


# ───────── пользователи ─────────

@router.get("/users")
def users_list(request: Request):
    return users.listing(auth.user(request))


@router.post("/users")
def users_create(request: Request, body: dict[str, Any] = Body(...)):
    return {"id": users.create(auth.user(request), body)}


@router.patch("/users/{user_id}")
def users_update(user_id: int, request: Request, body: dict[str, Any] = Body(...)):
    users.update(auth.user(request), user_id, body)
    return {"ok": True}


@router.post("/clients/{client_id}/topup")
def topup(client_id: int, body: TopUp, request: Request):
    return {"balance": billing.topup(client_id, body.amount, auth.user(request).id, body.note.strip())}


@router.get("/clients/{client_id}/ledger")
def client_ledger(client_id: int, request: Request):
    return users.finance(auth.user(request), client_id)


@router.put("/markup")
def markup(request: Request, body: dict[str, Any] = Body(...)):
    users.set_default_markup(auth.user(request), body.get("markup", 1))
    return {"ok": True}


# ───────── ключи Polza ─────────

@router.get("/keys")
def keys_list(request: Request, refresh: bool = False):
    return users.keys_listing(auth.user(request), refresh)


@router.post("/keys")
def keys_create(request: Request, body: dict[str, Any] = Body(...)):
    return {"id": users.key_save(auth.user(request), None, body)}


@router.patch("/keys/{key_id}")
def keys_update(key_id: int, request: Request, body: dict[str, Any] = Body(...)):
    users.key_save(auth.user(request), key_id, body)
    return {"ok": True}


@router.delete("/keys/{key_id}")
def keys_delete(key_id: int, request: Request):
    users.key_delete(auth.user(request), key_id)
    return {"ok": True}


# ───────── финансы ─────────

@router.get("/finance")
def finance(request: Request, client_id: int | None = None):
    return users.finance(auth.user(request), client_id)
