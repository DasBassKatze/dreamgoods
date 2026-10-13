"""Совместимость: «админ» теперь — мастер-аккаунт (см. core/auth.py)."""
from fastapi import Request

from .auth import Forbidden, master


def is_admin(request: Request) -> bool:
    u = getattr(request.state, "user", None)
    return bool(u and u.master)


def required(request: Request):
    master(request)


__all__ = ["Forbidden", "is_admin", "required"]
