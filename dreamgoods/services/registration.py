"""Регистрация на сайте с подтверждением почты.

1. Посетитель заполняет форму: почта, имя или название магазина, пароль, согласия (обязательные документы).
2. Создаются кабинет (тариф «Старт», оплата через баланс), основной проект и учётная запись с неподтверждённой
   почтой; согласия пишутся в журнал (версия документа, IP, браузер).
3. На почту уходит ссылка /verify?token=… (действует 48 часов). До подтверждения войти нельзя.
4. Переход по ссылке подтверждает почту и сразу открывает сессию.
"""
import hashlib
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import db
from ..core import auth, legal as L, mailer
from ..core.logs import log
from ..db.models import Client, EmailToken, Organization, Project, User
from . import consents

TOKEN_TTL = timedelta(hours=48)
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

# ограничения частоты: регистраций с адреса и повторных писем на почту
_hits, _lock = {}, threading.Lock()


def _limit(key, n, seconds, msg, count=True):
    """count=False — только проверка (попытка засчитывается отдельно, после успеха)."""
    now = time.time()
    with _lock:
        lst = [t for t in _hits.get(key, []) if now - t < seconds]
        if len(lst) >= n:
            raise auth.Forbidden(msg)
        if count:
            lst.append(now)
        _hits[key] = lst


def _utcnow():
    return datetime.now(timezone.utc)


def _new_token(s, user_id):
    token = secrets.token_urlsafe(32)
    s.add(EmailToken(id=hashlib.sha256(token.encode()).hexdigest(), user_id=user_id, kind="verify",
                     expires_at=_utcnow() + TOKEN_TTL))
    return token


def _link(base_url, token):
    base = mailer.PUBLIC_URL or (base_url or "").rstrip("/")
    return f"{base}/verify?token={token}"


def register(email, name, password, accepted, ip, agent, base_url):
    email = (email or "").strip().lower()
    name = (name or "").strip()[:200]
    if not EMAIL_RX.match(email) or len(email) > 200:
        raise ValueError("укажите настоящий адрес почты — на него придёт ссылка для подтверждения")
    auth.validate_password(password)
    if len(name) < 2:
        raise ValueError("укажите имя или название магазина")
    accepted = [k for k in dict.fromkeys(accepted or []) if k in L.REGISTER_KINDS]
    REG_MSG = "слишком много регистраций с этого адреса — попробуйте через час"
    _limit(f"reg:{ip}", 5, 3600, REG_MSG, count=False)
    with db.session() as s:
        org = s.get(Organization, consents.first_org_id(s))
        if not org or not consents.registration_open(org):
            raise auth.Forbidden("регистрация на сайте сейчас закрыта — напишите нам, и мы заведём кабинет")
        docs = consents.current(s, org.id)
        missing = [docs[k].title for k in L.REGISTER_KINDS if k in docs and docs[k].required and k not in accepted]
        if missing:
            raise ValueError("нужно согласие: " + "; ".join(missing))
        if s.scalar(select(User.id).where(User.email == email)):
            raise ValueError("на эту почту уже есть учётная запись — войдите или запросите письмо повторно")
        cname, n = name, 1
        while s.scalar(select(Client.id).where(Client.org_id == org.id, Client.name == cname)):
            n += 1
            cname = f"{name} ({n})"
        c = Client(org_id=org.id, name=cname, billing=True, plan="start")
        s.add(c)
        s.flush()
        s.add(Project(client_id=c.id, name="Основной проект", settings={}))
        u = User(org_id=org.id, email=email, name=name, role="user", password_hash=auth.hash_password(password),
                 client_id=c.id, active=True, email_verified_at=None)
        s.add(u)
        s.flush()
        consents.record(s, org.id, u, accepted, "register", ip, agent, docs=docs)
        token = _new_token(s, u.id)
    _limit(f"reg:{ip}", 5, 3600, REG_MSG)          # засчитываются только состоявшиеся регистрации
    log.info("Регистрация: %s («%s») с %s, согласия: %s", email, cname, ip or "?", ", ".join(accepted))
    sent = mailer.verify_email(email, name, _link(base_url, token))
    return {"ok": True, "email": email, "sent": sent}


def verify(token, ip, agent):
    """Ссылка из письма → почта подтверждена и сразу вход. → (токен сессии, CurrentUser)."""
    h = hashlib.sha256((token or "").encode()).hexdigest()
    with db.session() as s:
        t = s.get(EmailToken, h)
        if not t or t.kind != "verify":
            raise ValueError("ссылка недействительна — запросите письмо повторно")
        u = s.get(User, t.user_id)
        if t.used_at is not None and u and u.email_verified_at:
            raise ValueError("почта уже подтверждена — войдите с паролем")
        if t.expires_at < _utcnow():
            raise ValueError("срок ссылки истёк — запросите письмо повторно")
        if not u or not u.active:
            raise ValueError("учётная запись не найдена или отключена")
        t.used_at = _utcnow()
        u.email_verified_at = u.email_verified_at or _utcnow()
        user_id = u.id
    log.info("Почта подтверждена: user %s", user_id)
    return auth.open_session(user_id, ip, agent)


def resend(email, ip, base_url):
    """Повторное письмо. Ответ всегда одинаковый — по нему нельзя узнать, есть ли такая почта."""
    email = (email or "").strip().lower()
    _limit(f"resend:{ip}", 5, 3600, "слишком много запросов — попробуйте позже")
    _limit(f"resend:{email}", 1, 60, "письмо уже отправлено — подождите минуту")
    with db.session() as s:
        u = s.scalar(select(User).where(User.email == email))
        if not u or u.email_verified_at or not u.active:
            return {"ok": True}
        token = _new_token(s, u.id)
        name = u.name
    mailer.verify_email(email, name, _link(base_url, token))
    return {"ok": True}


def confirm_by_master(cu, user_id):
    """Мастер подтверждает почту вручную (например, если почта сервиса ещё не настроена)."""
    with db.session() as s:
        u = s.get(User, user_id)
        if not u or u.org_id != cu.org_id:
            raise LookupError("пользователь не найден")
        u.email_verified_at = u.email_verified_at or _utcnow()
    log.info("Почта %s подтверждена мастером %s", user_id, cu.email)
