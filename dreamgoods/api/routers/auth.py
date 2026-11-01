"""Вход и выход, текущий пользователь, смена пароля."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ...core import auth
from ...services import registration, users

router = APIRouter(prefix="/api/auth", tags=["вход"])


class LoginBody(BaseModel):
    email: str
    password: str


class RegisterBody(BaseModel):
    email: str
    name: str
    password: str
    accepted: list[str] = []         # виды документов, на которые пользователь поставил галочки


class TokenBody(BaseModel):
    token: str


class EmailBody(BaseModel):
    email: str


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


def _client(request: Request):
    return (request.client.host if request.client else ""), request.headers.get("user-agent", "")


def _set_cookie(request, response, token):
    response.set_cookie(auth.COOKIE, token, max_age=int(auth.TTL.total_seconds()), httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


@router.post("/register")
def register(body: RegisterBody, request: Request):
    """Регистрация: кабинет + учётная запись с неподтверждённой почтой, согласия — в журнал, письмо со ссылкой."""
    ip, agent = _client(request)
    return registration.register(body.email, body.name, body.password, body.accepted, ip, agent, str(request.base_url))


@router.post("/verify")
def verify(body: TokenBody, request: Request, response: Response):
    """Ссылка из письма: почта подтверждена — сразу вход."""
    ip, agent = _client(request)
    token, _ = registration.verify(body.token, ip, agent)
    _set_cookie(request, response, token)
    request.state.user = auth.user_by_token(token)
    return users.me(request.state.user)


@router.post("/resend")
def resend(body: EmailBody, request: Request):
    ip, _ = _client(request)
    return registration.resend(body.email, ip, str(request.base_url))
