"""Вход на сайт: пароли (scrypt), сессии в базе (cookie HttpOnly), текущий пользователь запроса.

Роли: master — мастер-аккаунт (всё видит, заводит пользователей, пополняет балансы, управляет ключами Polza);
user — личный кабинет, видит только проекты своего клиента.
"""
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import delete, select

from .. import db
from ..db.models import Session, User
from . import config
from .events import utcnow
from .logs import log

COOKIE = "dg_session"
TTL = timedelta(days=30)
PUBLIC = ("/api/auth/login", "/api/auth/logout", "/api/health")


class Unauthorized(PermissionError):
    status = 401


class Forbidden(PermissionError):
    status = 403


@dataclass(frozen=True)
class CurrentUser:
    id: int
    org_id: int
    email: str
    name: str
    role: str
    client_id: int | None

    @property
    def master(self):
        return self.role == "master"


# ───────── пароли ─────────

def hash_password(password):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(password, stored):
    try:
        algo, salt, h = (stored or "").split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt((password or "").encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


def validate_password(password):
    if len(password or "") < 6:
        raise ValueError("пароль — не короче 6 символов")


# ───────── защита от подбора: не больше 10 неудачных входов с адреса за 10 минут ─────────
_fails, _fails_lock = {}, threading.Lock()


def _too_many(ip):
    now = time.time()
    with _fails_lock:
        lst = [t for t in _fails.get(ip, []) if now - t < 600]
        _fails[ip] = lst
        return len(lst) >= 10


def _fail(ip):
    with _fails_lock:
        _fails.setdefault(ip, []).append(time.time())


# ───────── сессии ─────────
_cache, _cache_lock = {}, threading.Lock()      # sha256(токен) → (CurrentUser, до какого времени верить кэшу)


def _sid(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(email, password, ip="", agent=""):
    """→ (токен для cookie, CurrentUser). Сообщение об ошибке одинаковое для «нет такого» и «неверный пароль»."""
    if _too_many(ip):
        raise Forbidden("слишком много попыток входа — подождите 10 минут")
    with db.session() as s:
        u = s.scalar(select(User).where(User.email == (email or "").strip().lower()))
        if not u or not u.active or not check_password(password, u.password_hash):
            _fail(ip)
            raise Unauthorized("неверный логин или пароль")
        token = secrets.token_urlsafe(32)
        s.add(Session(id=_sid(token), user_id=u.id, expires_at=utcnow() + TTL, ip=ip[:64], agent=(agent or "")[:300]))
        u.last_login_at = utcnow()
        cu = _current(u)
    log.info("Вход: %s (%s) с %s", cu.email, cu.role, ip or "?")
    return token, cu


def logout(token):
    if not token:
        return
    with db.session() as s:
        s.execute(delete(Session).where(Session.id == _sid(token)))
    with _cache_lock:
        _cache.pop(_sid(token), None)


def drop_user_sessions(user_id, keep_token=None):
    """Выход со всех устройств (после смены пароля или блокировки)."""
    keep = _sid(keep_token) if keep_token else None
    with db.session() as s:
        q = delete(Session).where(Session.user_id == user_id)
        if keep:
            q = q.where(Session.id != keep)
        s.execute(q)
    with _cache_lock:
        for k in [k for k, (u, _) in _cache.items() if u.id == user_id and k != keep]:
            _cache.pop(k, None)


def _current(u):
    return CurrentUser(id=u.id, org_id=u.org_id, email=u.email, name=u.name or u.email, role=u.role, client_id=u.client_id)


def user_by_token(token):
    if not token:
        return None
    sid = _sid(token)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(sid)
    if hit and hit[1] > now:
        return hit[0]
    with db.session() as s:
        sess = s.get(Session, sid)
        if not sess or sess.expires_at < utcnow():
            return None
        u = s.get(User, sess.user_id)
        if not u or not u.active:
            return None
        cu = _current(u)
    with _cache_lock:
        _cache[sid] = (cu, now + 20)        # 20 с без запроса к базе (картинки грузятся пачками)
    return cu


def forget_cache():
    with _cache_lock:
        _cache.clear()


def token_of(request: Request):
    t = request.cookies.get(COOKIE) or ""
    if not t:
        h = request.headers.get("Authorization") or ""
        t = h[7:] if h.lower().startswith("bearer ") else ""
    return t


def user(request: Request) -> CurrentUser:
    u = getattr(request.state, "user", None)
    if u is None:
        raise Unauthorized("войдите на сайт")
    return u


def master(request: Request) -> CurrentUser:
    u = user(request)
    if not u.master:
        raise Forbidden("доступно только мастер-аккаунту")
    return u


# ───────── первый запуск ─────────

def bootstrap_master(org_id):
    """Мастер-аккаунт из .env (DREAMGOODS_ADMIN_EMAIL / DREAMGOODS_ADMIN_PASSWORD), если в базе ещё нет мастера с паролем."""
    email = config.app_env("ADMIN_EMAIL", "admin").strip().lower()
    password = config.app_env("ADMIN_PASSWORD", "")
    with db.session() as s:
        if s.scalar(select(User.id).where(User.role == "master", User.password_hash != "")):
            return
        if not password or password == "admin" or len(password) < 12:
            raise ValueError("задайте DREAMGOODS_ADMIN_PASSWORD: минимум 12 символов; пароль admin запрещён")
        u = s.scalar(select(User).where(User.role == "master").order_by(User.id)) or \
            s.scalar(select(User).where(User.email == email))
        if not u:
            u = User(org_id=org_id, email=email, name="Мастер", role="master")
            s.add(u)
        u.email, u.role, u.active, u.password_hash = email, "master", True, hash_password(password)
        if not u.name or u.name == "Владелец":
            u.name = "Мастер"
    log.warning("Создан мастер-аккаунт: логин «%s», пароль из DREAMGOODS_ADMIN_PASSWORD%s", email,
                " (по умолчанию admin — смените после входа!)" if password == "admin" else "")

