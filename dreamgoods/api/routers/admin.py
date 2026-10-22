"""Мастер-панель: пользователи, ключи Polza, финансы, метрики и расходы, очередь, журнал сервера."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ... import db
from ...core import auth
from ...db.models import Organization
from ...services import admin as svc
from ...services import billing, consents, moderation, plans, qc_export, registration, reports, topups, users
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

@router.get("/report")
def report(request: Request, date_from: str = "", date_to: str = "", client_id: int | None = None, usn_rate: float = 0.06,
           format: str = "json", metrics: str = "", sections: str = "", cols: str = ""):
    """Отчёт за период: деньги клиентов, себестоимость Polza, наценка, объём работы. format=csv — файл для Excel.
    metrics, sections, cols — что включить в CSV (ключи через запятую; пусто — всё, «none» — ничего из группы)."""
    rep = reports.build(auth.user(request), date_from or None, date_to or None, client_id, max(0.0, min(usn_rate, 0.2)))
    if format == "csv":
        name = f"dreamgoods_report_{rep['from']}_{rep['to']}.csv"
        sel = lambda v, allowed: [] if v == "none" else reports.pick(v, allowed)
        body = reports.to_csv(rep, sel(metrics, reports.METRICS), sel(sections, reports.SECTIONS), sel(cols, reports.CLIENT_COLS))
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return rep


@router.get("/topups")
def topup_requests(request: Request, status: str = ""):
    return {"items": topups.listing(auth.user(request), status)}


@router.post("/topups/{request_id}/{action}")
def topup_resolve(request_id: int, action: str, request: Request):
    """action: paid — зачислить сумму с бонусом пакета, cancel — отклонить."""
    return topups.resolve(auth.user(request), request_id, action)


@router.get("/plans")
def plans_get(request: Request):
    with db.session() as s:
        org = s.get(Organization, auth.user(request).org_id)
        st = dict(org.settings or {})
    return plans.public_plans(st) | {"defaults": plans.P.DEFAULTS, "overrides": st.get("plans") or {}}


@router.put("/plans")
def plans_put(request: Request, body: dict[str, Any] = Body(...)):
    """Условия тарифов: {seller: {price, projects, …}, …}; хранятся только отличия от значений по умолчанию."""
    plans.save_overrides(auth.user(request).org_id, body.get("plans") or {})
    return plans_get(request)


@router.get("/moderation")
def moderation_log(request: Request):
    """Журнал модерации: что сервис остановил (запросы, готовые кадры, загруженные фото)."""
    return {"items": moderation.listing(auth.user(request).org_id)}


@router.get("/qc-export")
def qc_export_zip(request: Request, project_id: int | None = None, days: int | None = None, images: str = "disputed"):
    """ZIP с данными ИИ-проверки для разбора: CSV проверок, ручных решений, профилей товаров и картинки спорных кадров."""
    data, _ = qc_export.build(auth.user(request).org_id, project_id, days, images if images in ("none", "disputed", "all")
                              else "disputed")
    from datetime import date
    name = f"dreamgoods_qc_{date.today().isoformat()}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/finance")
def finance(request: Request, client_id: int | None = None):
    return users.finance(auth.user(request), client_id)


class LegalDocBody(BaseModel):
    title: str = ""
    body: str = ""
    required: bool = True


class RegistrationBody(BaseModel):
    open: bool


@router.get("/legal")
def legal_docs(request: Request):
    """Документы (текущие версии с историей), открыта ли регистрация, настроена ли почта."""
    return consents.admin_docs(auth.user(request))


@router.put("/legal/{kind}")
def legal_save(kind: str, body: LegalDocBody, request: Request):
    """Сохранить документ — новая версия; обязательные пользователи примут заново при входе."""
    return consents.admin_save(auth.user(request), kind, body.title, body.body, body.required)


@router.put("/registration")
def registration_toggle(body: RegistrationBody, request: Request):
    return consents.set_registration(auth.user(request), body.open)


@router.get("/consents")
def consents_journal(request: Request, kind: str = "", q: str = "", format: str = ""):
    """Журнал согласий; format=csv — файл для юриста."""
    cu = auth.user(request)
    if format == "csv":
        return Response(consents.journal_csv(cu, kind, q), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="consents.csv"'})
    return {"items": consents.journal(cu, kind, q)}


@router.post("/users/{user_id}/verify")
def verify_user(user_id: int, request: Request):
    """Подтвердить почту пользователя вручную."""
    registration.confirm_by_master(auth.user(request), user_id)
    return {"ok": True}
