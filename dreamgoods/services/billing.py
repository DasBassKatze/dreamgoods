"""Внутренний баланс клиентов.

Каждая оплаченная операция (генерация, правка, ИИ-проверка, профиль товара, образ модели…) уже пишется в журнал
расходов (usage_ledger, себестоимость Polza). Для клиентов с billing=True одновременно списывается сумма
с наценкой (наценка клиента или общая из настроек мастера) — в журнал баланса (balance_ledger).
Мастер пополняет балансы вручную. При нулевом балансе новые платные задания не ставятся.
"""
import contextvars

from sqlalchemy import func, select, text

from .. import db
from ..core.logs import log
from ..core.money import decimal, money
from ..db.models import BalanceEntry, Client, Organization, Project

KIND_RU = {"generation": "генерация кадра", "edit": "правка фото", "qc": "ИИ-проверка", "count": "ИИ-проверка",
           "spec": "ИИ-проверка", "views": "разбор референсов", "profile": "профиль товара", "sort": "разбор импорта",
           "persona": "модель клиента", "persona_image": "образ модели", "style": "оформление"}


# Кто запустил текущее действие: мастер платит напрямую с Polza — внутренний баланс кабинета не проверяется
# и не списывается. Ставится из запроса (API) и переносится в задания очереди (payload.by_master).
by_master = contextvars.ContextVar("dg_by_master", default=False)


class NoFunds(ValueError):
    status = 402


def default_markup(org):
    try:
        value = (org.settings or {}).get("markup")
        return max(0.0, float(decimal(1 if value is None else value)))
    except (TypeError, ValueError):
        return 1.0


def markup_of(client, org):
    return client.markup if client.markup is not None else default_markup(org)


def charge(s, project_id, usage, tag=""):
    """usage — список расходов операции [{kind, cost}] (из Trace). Списывает с баланса клиента проекта."""
    cost = sum((decimal(u.get("cost")) for u in usage), decimal(0))
    if cost <= 0 or not project_id or by_master.get():
        return 0.0
    project = s.get(Project, project_id)
    if not project:
        return 0.0
    client = s.get(Client, project.client_id, with_for_update=True, populate_existing=True)     # параллельные задания не «съедят» баланс дважды
    if not client or not client.billing:
        return 0.0
    amount = money(cost * decimal(markup_of(client, s.get(Organization, client.org_id))))
    if amount <= 0:
        return 0.0
    client.balance_rub = money(decimal(client.balance_rub) - decimal(amount))
    kinds = []
    for u in usage:
        k = KIND_RU.get(u.get("kind"), u.get("kind") or "")
        if k and k not in kinds:
            kinds.append(k)
    what = (", ".join(kinds) + (f" · {tag.strip('[]')}" if tag else ""))[:200]
    s.add(BalanceEntry(client_id=client.id, project_id=project_id, kind="charge", amount_rub=-amount, cost_rub=money(cost, 6),
                       balance_after=client.balance_rub, what=what))
    return amount


def credit(s, client, amount, user_id, note=""):
    """Зачисление внутри транзакции вызывающего кода; строка клиента должна быть заблокирована."""
    amount = money(amount)
    if amount == 0:
        raise ValueError("укажите сумму")
    client.balance_rub = money(decimal(client.balance_rub) + decimal(amount))
    s.add(BalanceEntry(client_id=client.id, user_id=user_id, kind="topup" if amount > 0 else "adjust",
                       amount_rub=amount, balance_after=client.balance_rub,
                       what=(note or ("пополнение" if amount > 0 else "списание вручную"))[:200]))
    return client.balance_rub


def topup(client_id, amount, user_id, note=""):
    with db.session() as s:
        c = s.get(Client, int(client_id), with_for_update=True)
        if not c:
            raise LookupError("клиент не найден")
        bal = credit(s, c, amount, user_id, note)
        name = c.name
    log.info("Баланс клиента «%s»: %+.2f ₽ → %.2f ₽ %s", name, float(amount), bal, note)
    return bal


def client_of_project(s, project_id):
    p = s.get(Project, project_id)
    return s.get(Client, p.client_id) if p else None


def ensure_funds(project_id):
    """Перед платным заданием: у клиента с балансом должно быть больше нуля (мастера это не касается)."""
    if by_master.get():
        return
    with db.session() as s:
        c = client_of_project(s, project_id)
        from .payments import held
        if c and c.billing and decimal(c.balance_rub) - decimal(held(s, c.id)) <= 0:
            raise NoFunds(f"На балансе {c.balance_rub:.2f} ₽ — пополните баланс, чтобы запускать генерацию "
                          "(обратитесь к администратору сервиса)")


def has_funds(project_id):
    if by_master.get():
        return True
    with db.session() as s:
        c = client_of_project(s, project_id)
        from .payments import held
        return not (c and c.billing and decimal(c.balance_rub) - decimal(held(s, c.id)) <= 0)


def account(client_id, limit=200):
    with db.session() as s:
        c = s.get(Client, client_id)
        if not c:
            raise LookupError("клиент не найден")
        org = s.get(Organization, c.org_id)
        rows = s.scalars(select(BalanceEntry).where(BalanceEntry.client_id == c.id).order_by(BalanceEntry.id.desc())
                         .limit(limit)).all()
        month = s.scalar(select(func.coalesce(func.sum(BalanceEntry.amount_rub), 0)).where(
            BalanceEntry.client_id == c.id, BalanceEntry.kind == "charge",
            BalanceEntry.created_at >= func.date_trunc("month", func.now())))
        op = func.split_part(BalanceEntry.what, " · ", 1)
        prices = s.execute(select(op, func.count(BalanceEntry.id), func.avg(BalanceEntry.amount_rub))
                           .where(BalanceEntry.client_id == c.id, BalanceEntry.kind == "charge",
                                  BalanceEntry.created_at >= func.now() - text("interval '90 days'"))
                           .group_by(op).order_by(func.count(BalanceEntry.id).desc())).all()
        from .payments import held
        reserved = held(s, c.id)
        return {"balance": round(c.balance_rub or 0, 2), "reserved": reserved,
                "available": money(decimal(c.balance_rub) - decimal(reserved)), "billing": c.billing, "markup": markup_of(c, org),
                "spent_month": abs(round(float(month or 0), 2)),
                "prices": [{"what": w or "прочее", "count": n, "avg": abs(round(float(a or 0), 2))} for w, n, a in prices],
                "entries": [entry_view(e) for e in rows]}


def entry_view(e, master=False):
    v = {"id": e.id, "kind": e.kind, "amount": round(e.amount_rub, 2), "balance_after": round(e.balance_after, 2),
         "what": e.what, "project_id": e.project_id, "created": e.created_at.isoformat() if e.created_at else None}
    if master:
        v["cost"] = round(e.cost_rub or 0, 2)
        v["client_id"] = e.client_id
    return v

