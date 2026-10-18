"""Пользователи сайта (для мастер-аккаунта): заведение, личные кабинеты, ключи Polza, балансы."""
from datetime import datetime

from sqlalchemy import func, select

from .. import db
from ..ai import polza
from ..core import auth, keys, plans as plans_core
from ..core.logs import log
from ..db.models import (BalanceEntry, Client, Organization, PolzaKey, Project, UsageEntry, User)
from . import billing, plans


def _org(s, u):
    return s.get(Organization, u.org_id)


def me(cu):
    with db.session() as s:
        u = s.get(User, cu.id)
        c = s.get(Client, u.client_id) if u.client_id else None
        org = s.get(Organization, u.org_id)
        out = {"id": u.id, "email": u.email, "name": u.name or u.email, "role": u.role,
               "client": {"id": c.id, "name": c.name, "balance": round(c.balance_rub or 0, 2), "billing": c.billing,
                          "plan": plans.view(c, org.settings if org else {}) if c.billing else None}
               if c else None}
        return out


def change_password(cu, old, new, token):
    auth.validate_password(new)
    with db.session() as s:
        u = s.get(User, cu.id)
        if not auth.check_password(old, u.password_hash):
            raise ValueError("текущий пароль указан неверно")
        u.password_hash = auth.hash_password(new)
    auth.drop_user_sessions(cu.id, keep_token=token)


# ───────── мастер: пользователи ─────────

def listing(cu):
    with db.session() as s:
        users = s.scalars(select(User).where(User.org_id == cu.org_id).order_by(User.role.desc(), User.id)).all()
        clients = {c.id: c for c in s.scalars(select(Client).where(Client.org_id == cu.org_id)).all()}
        org = _org(s, cu)
        nproj = dict(s.execute(select(Project.client_id, func.count(Project.id)).where(Project.archived.is_(False))
                               .group_by(Project.client_id)).all())
        month = dict(s.execute(select(BalanceEntry.client_id, func.sum(BalanceEntry.amount_rub))
                               .where(BalanceEntry.kind == "charge", BalanceEntry.created_at >= func.date_trunc("month", func.now()))
                               .group_by(BalanceEntry.client_id)).all())
        cost_month = dict(s.execute(select(Project.client_id, func.sum(UsageEntry.amount_rub))
                                    .join(Project, Project.id == UsageEntry.project_id)
                                    .where(UsageEntry.created_at >= func.date_trunc("month", func.now()))
                                    .group_by(Project.client_id)).all())
        key_names = {k.id: k.name for k in s.scalars(select(PolzaKey).where(PolzaKey.org_id == cu.org_id)).all()}
        out = []
        for u in users:
            c = clients.get(u.client_id)
            out.append({"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
                        "last_login": u.last_login_at.isoformat() if u.last_login_at else None,
                        "created": u.created_at.isoformat() if u.created_at else None,
                        "client": None if not c else {
                            "id": c.id, "name": c.name, "balance": round(c.balance_rub or 0, 2), "billing": c.billing,
                            "markup": c.markup, "markup_effective": billing.markup_of(c, org), "key_id": c.key_id,
                            "key_name": key_names.get(c.key_id, ""), "projects": nproj.get(c.id, 0),
                            "charged_month": abs(round(float(month.get(c.id) or 0), 2)),
                            "cost_month": round(float(cost_month.get(c.id) or 0), 2),
                            "plan": c.plan or "start", "plan_until": c.plan_until.isoformat() if c.plan_until else None,
                            "plan_effective": plans_core.effective_key(c)}})
        free = [{"id": c.id, "name": c.name, "projects": nproj.get(c.id, 0)} for c in clients.values()
                if not any(u.client_id == c.id for u in users)]
        return {"users": out, "unassigned_clients": free, "markup": billing.default_markup(org)}


def create(cu, data):
    email = str(data.get("email") or "").strip().lower()
    if len(email) < 3:
        raise ValueError("укажите логин или почту")
    password = str(data.get("password") or "")
    auth.validate_password(password)
    role = "master" if data.get("role") == "master" else "user"
    with db.session() as s:
        if s.scalar(select(User.id).where(User.email == email)):
            raise ValueError(f"пользователь «{email}» уже есть")
        name = str(data.get("name") or "").strip() or email
        client_id = None
        if role == "user":
            if data.get("client_id"):           # отдать пользователю существующего клиента (с его проектами)
                c = s.get(Client, int(data["client_id"]))
                if not c or c.org_id != cu.org_id:
                    raise LookupError("клиент не найден")
                from .plans import check_new_user
                check_new_user(s, c)
            else:
                cname = name
                n = 1
                while s.scalar(select(Client.id).where(Client.org_id == cu.org_id, Client.name == cname)):
                    n += 1
                    cname = f"{name} ({n})"
                c = Client(org_id=cu.org_id, name=cname)
                s.add(c)
                s.flush()
                s.add(Project(client_id=c.id, name="Основной проект", settings={}))
            c.billing = data.get("billing", True) is not False
            if data.get("markup") not in (None, ""):
                c.markup = max(0.0, float(data["markup"]))
            client_id = c.id
        u = User(org_id=cu.org_id, email=email, name=name, role=role, password_hash=auth.hash_password(password),
                 client_id=client_id, active=True)
        s.add(u)
        s.flush()
        uid = u.id
    if role == "user" and float(data.get("balance") or 0):
        billing.topup(client_id, float(data["balance"]), cu.id, "стартовый баланс")
    log.info("Мастер %s создал пользователя %s (%s)", cu.email, email, role)
    return uid


def update(cu, user_id, data):
    with db.session() as s:
        u = s.get(User, int(user_id))
        if not u or u.org_id != cu.org_id:
            raise LookupError("пользователь не найден")
        if "name" in data and data["name"] is not None:
            u.name = str(data["name"]).strip()[:200]
        if data.get("email"):
            e = str(data["email"]).strip().lower()
            if e != u.email and s.scalar(select(User.id).where(User.email == e)):
                raise ValueError(f"логин «{e}» уже занят")
            u.email = e
        if "active" in data and data["active"] is not None:
            if u.id == cu.id and not data["active"]:
                raise ValueError("нельзя заблокировать самого себя")
            u.active = bool(data["active"])
        if data.get("password"):
            auth.validate_password(data["password"])
            u.password_hash = auth.hash_password(data["password"])
        c = s.get(Client, u.client_id) if u.client_id else None
        if c and u.role == "master" and data.get("billing"):
            raise ValueError("кабинет мастера работает напрямую с баланса Polza — внутренний баланс ему не нужен")
        if c:
            if "markup" in data:
                c.markup = None if data["markup"] in (None, "") else max(0.0, float(data["markup"]))
            if "billing" in data and data["billing"] is not None:
                c.billing = bool(data["billing"])
            if "key_id" in data:
                kid = int(data["key_id"] or 0)
                if kid and not s.get(PolzaKey, kid):
                    raise LookupError("ключ не найден")
                c.key_id = kid or None
            if data.get("client_name"):
                c.name = str(data["client_name"]).strip()[:200]
            if data.get("plan"):                 # тариф: на N месяцев (продление) или до даты
                until = None
                if data.get("plan_until"):
                    until = datetime.fromisoformat(str(data["plan_until"])[:10])
                if data["plan"] not in plans_core.ORDER:
                    raise ValueError("неизвестный тариф")
                plans._apply(c, str(data["plan"]), data.get("plan_months"), until)
        dropped = data.get("password") or data.get("active") is False
    if dropped:
        auth.drop_user_sessions(int(user_id))
    auth.forget_cache()


def set_default_markup(cu, markup):
    with db.session() as s:
        org = _org(s, cu)
        org.settings = {**(org.settings or {}), "markup": max(0.0, float(markup))}


# ───────── мастер: ключи Polza ─────────

def keys_listing(cu, refresh=False):
    with db.session() as s:
        ks = s.scalars(select(PolzaKey).where(PolzaKey.org_id == cu.org_id).order_by(PolzaKey.id)).all()
        pinned = {}
        for c in s.scalars(select(Client).where(Client.org_id == cu.org_id, Client.key_id.is_not(None))).all():
            pinned.setdefault(c.key_id, []).append(c.name)
        pool = [k.id for k in keys.pool(s, cu.org_id)]
        clients = s.scalars(select(Client).where(Client.org_id == cu.org_id)).all()
        served = {}
        for c in clients:          # кто фактически работает на каком ключе
            _, kid = keys.for_client(s, c.id, cu.org_id)
            if kid:
                served.setdefault(kid, []).append(c.name)
        rows = [(k.id, k.name, k.secret, k.active, k.shared, k.note) for k in ks]
    out = []
    for kid, name, secret, active, shared, note in rows:
        b = polza.balance(secret, force=refresh)
        out.append({"id": kid, "name": name, "mask": keys.mask(secret), "active": active, "shared": shared, "note": note,
                    "in_pool": kid in pool, "pinned": pinned.get(kid, []), "serves": served.get(kid, []),
                    "balance": b["value"], "balance_error": b["error"]})
    return {"keys": out}


def key_save(cu, key_id, data):
    with db.session() as s:
        if key_id:
            k = s.get(PolzaKey, int(key_id))
            if not k or k.org_id != cu.org_id:
                raise LookupError("ключ не найден")
        else:
            secret = str(data.get("secret") or "").strip()
            if len(secret) < 10:
                raise ValueError("вставьте ключ API Polza")
            k = PolzaKey(org_id=cu.org_id, secret=secret)
            s.add(k)
        if data.get("secret") and key_id:
            k.secret = str(data["secret"]).strip()
        for f in ("name", "note"):
            if data.get(f) is not None:
                setattr(k, f, str(data[f]).strip()[:500])
        for f in ("active", "shared"):
            if data.get(f) is not None:
                setattr(k, f, bool(data[f]))
        if not k.name:
            k.name = f"Ключ …{k.secret[-4:]}"
        s.flush()
        kid, secret = k.id, k.secret
    polza.balance(secret, force=True)
    return kid


def key_delete(cu, key_id):
    with db.session() as s:
        k = s.get(PolzaKey, int(key_id))
        if not k or k.org_id != cu.org_id:
            raise LookupError("ключ не найден")
        s.delete(k)


# ───────── мастер: финансы ─────────

def finance(cu, client_id=None, limit=300):
    with db.session() as s:
        clients = {c.id: c.name for c in s.scalars(select(Client).where(Client.org_id == cu.org_id)).all()}
        q = select(BalanceEntry).where(BalanceEntry.client_id.in_(list(clients) or [0]))
        if client_id:
            q = q.where(BalanceEntry.client_id == int(client_id))
        rows = s.scalars(q.order_by(BalanceEntry.id.desc()).limit(limit)).all()

        def tot(kind, col, since_month=False):
            w = [BalanceEntry.kind == kind, BalanceEntry.client_id.in_(list(clients) or [0])]
            if since_month:
                w.append(BalanceEntry.created_at >= func.date_trunc("month", func.now()))
            return float(s.scalar(select(func.coalesce(func.sum(col), 0)).where(*w)) or 0)
        summary = {"revenue_month": abs(round(tot("charge", BalanceEntry.amount_rub, True), 2)),
                   "cost_month": round(tot("charge", BalanceEntry.cost_rub, True), 2),
                   "topups_month": round(tot("topup", BalanceEntry.amount_rub, True), 2),
                   "revenue_all": abs(round(tot("charge", BalanceEntry.amount_rub), 2)),
                   "cost_all": round(tot("charge", BalanceEntry.cost_rub), 2),
                   "balances": round(float(s.scalar(select(func.coalesce(func.sum(Client.balance_rub), 0))
                                                     .where(Client.org_id == cu.org_id, Client.billing.is_(True))) or 0), 2)}
        summary["margin_month"] = round(summary["revenue_month"] - summary["cost_month"], 2)
        entries = []
        for e in rows:
            v = billing.entry_view(e, master=True)
            v["client"] = clients.get(e.client_id, "")
            entries.append(v)
        return {"summary": summary, "entries": entries}
