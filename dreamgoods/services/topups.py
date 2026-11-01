"""Цены для сайта и заявки на пополнение баланса.
Пока онлайн-оплаты нет: пользователь оставляет заявку (сумма, способ оплаты), мастер после оплаты зачисляет её
одной кнопкой — сумма и бонус пакета приходят на баланс через обычное пополнение."""
from sqlalchemy import select

from .. import db
from ..core import plans as plans_core, presets as presets_core, pricing
from ..core.events import utcnow
from ..core.logs import log
from ..core.money import money
from ..db.models import Client, GenerationPreset, Organization, TopupRequest, User
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
        presets = None
        if org:
            rows = s.scalars(select(GenerationPreset).where(GenerationPreset.org_id == org.id, GenerationPreset.archived.is_(False),
                                                            GenerationPreset.client_id.is_(None))
                             .order_by(GenerationPreset.id)).all()
            if rows:
                presets = [{"name": p.name, "description": p.description, "quality": p.quality, "custom": p.custom or {},
                            "market": p.market, "total": presets_core.preset_total(p)} for p in rows]
        out = pricing.price_list(settings, markup, presets)
        from .plans import public_plans, view as plan_view
        out.update(public_plans(settings))
        out["my_plan"] = plan_view(client, settings) if client is not None and client.billing else None
        out["billing"] = bool(client and client.billing)
        out["balance"] = round(client.balance_rub or 0, 2) if client and client.billing else None
        out["signed_in"] = cu is not None
    return out


def _view(r, client_name="", user_email=""):
    return {"id": r.id, "client_id": r.client_id, "client": client_name, "user": user_email, "amount": round(r.amount_rub, 2),
            "bonus": round(r.bonus_rub or 0, 2), "method": r.method, "method_name": METHODS.get(r.method, r.method),
            "status": r.status, "note": r.note, "created": r.created_at.isoformat() if r.created_at else None,
            "resolved": r.resolved_at.isoformat() if r.resolved_at else None, "plan": r.plan or "", "months": r.months or 0,
            "plan_name": plans_core.DEFAULTS[r.plan]["name"] if r.plan in plans_core.DEFAULTS else ""}


def create(cu, amount, method, note="", plan="", months=0):
    if not cu.client_id:
        raise ValueError("у мастер-аккаунта нет своего баланса — генерации оплачиваются напрямую с Polza")
    try:
        amount = money(amount)
    except (TypeError, ValueError):
        raise ValueError("укажите сумму")
    plan = plan if plan in plans_core.ORDER and plan != "start" else ""
    months = 12 if plan and int(months or 0) >= 12 else (1 if plan else 0)
    if plan:                                  # оплата тарифа: сумма = цена × оплачиваемые месяцы, без бонуса пакета
        with db.session() as s:
            c0 = s.get(Client, cu.client_id)
            org = s.get(Organization, c0.org_id) if c0 else None
            price = plans_core.all_plans(org.settings if org else {})[plan]["price"]
        amount = float(price * (plans_core.YEAR_PAY_MONTHS if months == 12 else 1))
    if not pricing.MIN_TOPUP <= amount <= pricing.MAX_TOPUP:
        raise ValueError(f"сумма — от {pricing.MIN_TOPUP} до {pricing.MAX_TOPUP:,} ₽".replace(",", " "))
    if method not in METHODS:
        raise ValueError("выберите способ оплаты")
    bonus, _ = pricing.bonus_for(amount)
    if plan:
        bonus = 0.0
    with db.session() as s:
        c = s.get(Client, cu.client_id)
        if not c or not c.billing:
            raise ValueError("для вашего кабинета пополнение не требуется")
        if s.scalar(select(TopupRequest.id).where(TopupRequest.client_id == c.id, TopupRequest.status == "new")
                    .limit(1).offset(4)):
            raise ValueError("у вас уже 5 необработанных заявок — дождитесь зачисления")
        r = TopupRequest(client_id=c.id, user_id=cu.id, amount_rub=amount, bonus_rub=bonus, method=method,
                         note=(note or "").strip()[:2000], plan=plan, months=months)
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
        c = s.get(Client, r.client_id, with_for_update=True) if r else None
        if not r or not c or c.org_id != cu.org_id:
            raise LookupError("заявка не найдена")
        if r.status != "new":
            raise ValueError("заявка уже обработана")
        r.status, r.resolved_at = ("paid" if action == "paid" else "cancelled"), utcnow()
        amount, bonus, rid = r.amount_rub, r.bonus_rub or 0, r.id
        client_id = c.id
        if action == "paid" and r.plan:
            from .plans import activate_from_topup
            activate_from_topup(s, c, r.plan, r.months)
            log.info("Тариф «%s» для «%s» подключён по заявке №%s до %s", r.plan, c.name, rid, c.plan_until)
        if action == "paid":
            billing.credit(s, c, amount, cu.id, f"пополнение по заявке №{rid}")
            if bonus > 0:
                billing.credit(s, c, bonus, cu.id, f"бонус пакета к заявке №{rid}")
    return {"ok": True}

