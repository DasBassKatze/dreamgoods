"""Цены для сайта и заявки на пополнение баланса.
Пока онлайн-оплаты нет: пользователь оставляет заявку (сумма, способ оплаты), мастер после оплаты зачисляет её
одной кнопкой — сумма и бонус пакета приходят на баланс через обычное пополнение."""
from sqlalchemy import select

from .. import db
from ..core import pricing
from ..core.events import utcnow
from ..core.logs import log
from ..db.models import Client, Organization, TopupRequest, User
from . import billing

METHODS = {"card": "банковская карта", "sbp": "СБП", "invoice": "счёт для юрлица / ИП"}


def prices(cu=None):
    """Прайс с общей наценкой сервиса; вошедшему пользователю — с его личной наценкой."""
    with db.session() as s:
        org = s.get(Organization, cu.org_id) if cu else s.scalars(select(Organization).order_by(Organization.id)).first()
        settings = dict(org.settings or {}) if org else {}
        markup = billing.default_markup(org) if org else 1.0
        client = s.get(Client, cu.client_id) if cu and cu.client_id else None
        if client is not None and client.markup is not None:
            markup = client.markup
        out = pricing.price_list(settings, markup)
        out["billing"] = bool(client and client.billing)
        out["balance"] = round(client.balance_rub or 0, 2) if client and client.billing else None
        out["signed_in"] = cu is not None
    return out


def _view(r, client_name="", user_email=""):
    return {"id": r.id, "client_id": r.client_id, "client": client_name, "user": user_email, "amount": round(r.amount_rub, 2),
            "bonus": round(r.bonus_rub or 0, 2), "method": r.method, "method_name": METHODS.get(r.method, r.method),
            "status": r.status, "note": r.note, "created": r.created_at.isoformat() if r.created_at else None,
            "resolved": r.resolved_at.isoformat() if r.resolved_at else None}


def create(cu, amount, method, note=""):
    if not cu.client_id:
        raise ValueError("у мастер-аккаунта нет своего баланса — генерации оплачиваются напрямую с Polza")
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("укажите сумму")
    if not pricing.MIN_TOPUP <= amount <= pricing.MAX_TOPUP:
        raise ValueError(f"сумма — от {pricing.MIN_TOPUP} до {pricing.MAX_TOPUP:,} ₽".replace(",", " "))
    if method not in METHODS:
        raise ValueError("выберите способ оплаты")
    bonus, _ = pricing.bonus_for(amount)
    with db.session() as s:
        c = s.get(Client, cu.client_id)
        if not c or not c.billing:
            raise ValueError("для вашего кабинета пополнение не требуется")
        if s.scalar(select(TopupRequest.id).where(TopupRequest.client_id == c.id, TopupRequest.status == "new")
                    .limit(1).offset(4)):
            raise ValueError("у вас уже 5 необработанных заявок — дождитесь зачисления")
        r = TopupRequest(client_id=c.id, user_id=cu.id, amount_rub=amount, bonus_rub=bonus, method=method,
                         note=(note or "").strip()[:2000])
        s.add(r)
        s.flush()
        out = _view(r, c.name)
    log.info("Заявка на пополнение №%s: «%s» %.2f ₽ (+%.2f бонус), %s", out["id"], out["client"], amount, bonus, METHODS[method])
    return out


def mine(cu):
    if not cu.client_id:
        return []
    with db.session() as s:
        rows = s.scalars(select(TopupRequest).where(TopupRequest.client_id == cu.client_id)
                         .order_by(TopupRequest.id.desc()).limit(30)).all()
        return [_view(r) for r in rows]


def listing(cu, status=""):
    with db.session() as s:
        clients = {c.id: c.name for c in s.scalars(select(Client).where(Client.org_id == cu.org_id)).all()}
        q = select(TopupRequest).where(TopupRequest.client_id.in_(list(clients) or [0]))
        if status:
            q = q.where(TopupRequest.status == status)
        rows = s.scalars(q.order_by(TopupRequest.status != "new", TopupRequest.id.desc()).limit(200)).all()
        users = {u.id: u.email for u in s.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id} or {0}))).all()}
        return [_view(r, clients.get(r.client_id, ""), users.get(r.user_id, "")) for r in rows]


def resolve(cu, request_id, action):
    """action: paid — зачислить сумму с бонусом; cancel — отклонить."""
    if action not in ("paid", "cancel"):
        raise ValueError("неизвестное действие")
    with db.session() as s:
        r = s.get(TopupRequest, int(request_id), with_for_update=True)
        c = s.get(Client, r.client_id) if r else None
        if not r or not c or c.org_id != cu.org_id:
            raise LookupError("заявка не найдена")
        if r.status != "new":
            raise ValueError("заявка уже обработана")
        r.status, r.resolved_at = ("paid" if action == "paid" else "cancelled"), utcnow()
        amount, bonus, rid = r.amount_rub, r.bonus_rub or 0, r.id
        client_id = c.id
    if action == "paid":
        billing.topup(client_id, amount, cu.id, f"пополнение по заявке №{rid}")
        if bonus > 0:
            billing.topup(client_id, bonus, cu.id, f"бонус пакета к заявке №{rid}")
    return {"ok": True}
