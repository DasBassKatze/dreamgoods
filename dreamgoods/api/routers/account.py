"""Личный кабинет: баланс и история списаний."""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...core import auth
from ...services import billing, consents, projects, topups

router = APIRouter(prefix="/api/account", tags=["личный кабинет"])


@router.get("/balance")
def balance(request: Request):
    u = auth.user(request)
    if not u.client_id:
        return {"balance": None, "billing": False, "entries": [], "spent_month": 0, "markup": 1, "prices": []}
    out = billing.account(u.client_id)
    out.pop("markup", None)
    return out


@router.get("/storage")
def storage(request: Request):
    """Занятое место в хранилище и квота (мастер — по всему сервису)."""
    return projects.storage_usage(auth.user(request))


class TopupCreate(BaseModel):
    amount: float
    method: str = "card"
    note: str = ""
    plan: str = ""
    months: int = 0


@router.get("/topups")
def my_topups(request: Request):
    return {"items": topups.mine(auth.user(request))}


@router.post("/topups")
def create_topup(body: TopupCreate, request: Request):
    """Заявка на пополнение баланса: мастер зачислит её после оплаты."""
    return topups.create(auth.user(request), body.amount, body.method, body.note, body.plan, body.months)


public = APIRouter(prefix="/api/public", tags=["сайт"])


@public.get("/prices")
def prices(request: Request):
    """Цены для страницы «Цены и оплата» (вошедшему — с его наценкой)."""
    return topups.prices(getattr(request.state, "user", None))


class ConsentsBody(BaseModel):
    kinds: list[str]


def _client(request: Request):
    return (request.client.host if request.client else ""), request.headers.get("user-agent", "")


@router.get("/consents")
def my_consents(request: Request):
    """Документы сервиса и мои согласия (действующие версии)."""
    return {"items": consents.mine(auth.user(request))}


@router.post("/consents")
def accept_consents(body: ConsentsBody, request: Request):
    """Принять документы (новые версии обязательных — при входе; необязательные — в кабинете)."""
    ip, agent = _client(request)
    return {"items": consents.accept(auth.user(request), body.kinds, ip, agent)}


@router.post("/consents/{kind}/revoke")
def revoke_consent(kind: str, request: Request):
    ip, agent = _client(request)
    return {"items": consents.revoke(auth.user(request), kind, ip, agent)}


@public.get("/legal")
def legal_list():
    """Документы сервиса (для формы регистрации и подвала сайта) и открыта ли регистрация."""
    return consents.public_list()


@public.get("/legal/{kind}")
def legal_doc(kind: str, version: int = 0):
    return consents.document(kind, version or None)
