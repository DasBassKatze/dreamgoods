"""Мастер-панель: пользователи, ключи Polza, финансы, метрики и расходы, очередь, журнал сервера."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field

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



class ResolveOperation(BaseModel):
    cost_rub: float = Field(ge=0, allow_inf_nan=False)
    note: str = Field(min_length=5, max_length=500)

@router.get("/payments/pending")
def pending_payments():
    from sqlalchemy import select
    from ... import db
    from ...db.models import BillingOperation
    with db.session() as s:
        rows = s.scalars(select(BillingOperation).where(BillingOperation.status.in_(("uncertain", "submitted")))
            .order_by(BillingOperation.created_at).limit(200)).all()
        return {"items": [{"id": x.id, "client_id": x.client_id, "project_id": x.project_id,
            "reserved": x.reserved_rub, "task": x.external_id, "status": x.status, "created": x.created_at.isoformat()} for x in rows]}

@router.post("/payments/{operation_id}/resolve")
def resolve_payment(operation_id: str, body: ResolveOperation, request: Request):
    from ... import db
    from ...db.models import BillingOperation, Job
    from ...services.payments import settle
    from ...core.logs import log
    with db.session() as s:
        item = s.get(BillingOperation, operation_id)
        if not item:
            raise LookupError("операция не найдена")
        if item.external_id:
            from datetime import timedelta
            from ...core.events import utcnow
            if utcnow() - item.created_at < timedelta(days=1):
                raise ValueError("у операции есть задача Polza — используйте дозагрузку; ручная сверка доступна через сутки")
        job = s.get(Job, item.job_id) if item.job_id else None
        if item.status != "uncertain" or (job and job.status in ("queued", "running", "cancelling")):
            raise ValueError("операция ещё выполняется или уже сверена")
    settle(operation_id, body.cost_rub)
    log.warning("Сверка платежа %s мастером %s: стоимость %.2f; %s", operation_id, auth.user(request).id, body.cost_rub, body.note)
    return {"ok": True}

class ClientLimit(BaseModel):
    n: int = Field(ge=1, le=12)

@router.put("/clients/{client_id}/parallel")
def client_limit(client_id: int, body: ClientLimit):
    from ... import db
    from ...db.models import Client
    with db.session() as s:
        client = s.get(Client, client_id, with_for_update=True)
        if not client:
            raise LookupError("клиент не найден")
        client.parallel_limit = body.n
    return {"ok": True}


class ReservePrices(BaseModel):
    image: int = Field(ge=1, le=100000)
    chat: int = Field(ge=1, le=100000)

@router.put("/reserve-prices")
def reserve_prices(body: ReservePrices, request: Request):
    from ... import db
    from ...db.models import Organization
    with db.session() as s:
        org = s.get(Organization, auth.user(request).org_id, with_for_update=True)
        org.settings = {**(org.settings or {}), "reserve_image_rub":body.image, "reserve_chat_rub":body.chat}
    return {"ok":True}
