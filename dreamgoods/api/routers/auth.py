"""Вход и выход, текущий пользователь, смена пароля."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ...core import auth
from ...services import users

router = APIRouter(prefix="/api/auth", tags=["вход"])


class LoginBody(BaseModel):
    email: str
    password: str


class PasswordBody(BaseModel):
    old: str
    new: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else ""
    token, _ = auth.login(body.email, body.password, ip, request.headers.get("user-agent", ""))
    response.set_cookie(auth.COOKIE, token, max_age=int(auth.TTL.total_seconds()), httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    request.state.user = auth.user_by_token(token)
    return users.me(request.state.user)


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.logout(auth.token_of(request))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return users.me(auth.user(request))


@router.post("/password")
def password(body: PasswordBody, request: Request):
    users.change_password(auth.user(request), body.old, body.new, auth.token_of(request))
    return {"ok": True}
