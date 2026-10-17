"""Личный кабинет: баланс и история списаний."""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...core import auth
from ...services import billing, projects, topups

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


@router.get("/topups")
def my_topups(request: Request):
    return {"items": topups.mine(auth.user(request))}


@router.post("/topups")
def create_topup(body: TopupCreate, request: Request):
    """Заявка на пополнение баланса: мастер зачислит её после оплаты."""
    return topups.create(auth.user(request), body.amount, body.method, body.note)


public = APIRouter(prefix="/api/public", tags=["сайт"])


@public.get("/prices")
def prices(request: Request):
    """Цены для страницы «Цены и оплата» (вошедшему — с его наценкой)."""
    return topups.prices(getattr(request.state, "user", None))
