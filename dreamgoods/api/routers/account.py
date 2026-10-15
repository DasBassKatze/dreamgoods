"""Личный кабинет: баланс и история списаний."""
from fastapi import APIRouter, Request

from ...core import auth
from ...services import billing, projects

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
