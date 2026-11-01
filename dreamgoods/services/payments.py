"""Durable reservation per paid API call; all amounts exposed to clients include markup."""
from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from sqlalchemy import func, select
from .. import db
from ..db.models import BillingOperation, BalanceEntry, Client, GenerationRun, Job, Organization, Project, UsageEntry

job_context = ContextVar("billing_job", default=None)
operation_context = ContextVar("billing_operation", default=None)
retry_context = ContextVar("billing_retry", default=False)


def money(value):
    d = Decimal(str(value or 0))
    if not d.is_finite():
        raise ValueError("сумма должна быть конечным числом")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def held(s, client_id):
    return money(s.scalar(select(func.coalesce(func.sum(BillingOperation.reserved_rub), 0)).where(
        BillingOperation.client_id == client_id, BillingOperation.status.in_(("reserved", "submitted", "uncertain")))) or 0)


def estimate_call(s, org_id, model, kind):
    rows = list(s.scalars(select(UsageEntry.amount_rub).where(UsageEntry.org_id == org_id,
        UsageEntry.model == model, UsageEntry.kind == kind, UsageEntry.amount_rub > 0)
        .order_by(UsageEntry.id.desc()).limit(100)))
    org = s.get(Organization, org_id)
    fallback = (org.settings or {}).get("reserve_image_rub" if kind in ("generation", "edit", "persona_image") else "reserve_chat_rub")
    default = money(fallback or (50 if kind in ("generation", "edit", "persona_image") else 5))
    avg = sum(map(money, rows), Decimal(0)) / len(rows) if rows else default
    return money(avg), max(default, money(max(map(money, rows), default=default) * Decimal("1.25"))), len(rows)


def reserve(kind, model):
    from .billing import markup_of, NoFunds
    jid = job_context.get()
    if not jid:
        return None
    with db.session() as s:
        job = s.get(Job, jid)
        if not job.project_id:
            return None
        if kind == "generation":
            if job.kind == "persona":
                kind = "persona_image"
            elif (job.payload or {}).get("edit"):
                kind = "edit"
        p = s.get(Project, job.project_id)
        c = s.get(Client, p.client_id, with_for_update=True)
        org = s.get(Organization, c.org_id)
        _, upper, _ = estimate_call(s, c.org_id, model, kind)
        amount = money(upper * Decimal(str(markup_of(c, org)))) if c.billing else upper
        if c.billing and money(c.balance_rub) - held(s, c.id) < amount:
            raise NoFunds(f"недостаточно доступных средств для резерва {amount:.2f} ₽")
        if job.run_id:
            run = s.get(GenerationRun, job.run_id, with_for_update=True)
            rows = s.scalars(select(BillingOperation).where(BillingOperation.run_id == run.id,
                BillingOperation.status != "released")).all()
            total = sum((money(x.charged_rub if x.status == "settled" else x.reserved_rub) for x in rows), Decimal(0))
            retries = sum((money(x.charged_rub if x.status == "settled" else x.reserved_rub) for x in rows if x.is_retry), Decimal(0))
            if run.budget_rub is not None and total + amount > money(run.budget_rub):
                raise NoFunds("достигнут бюджет запуска")
            if retry_context.get() and run.retry_budget_rub is not None and retries + amount > money(run.retry_budget_rub):
                raise NoFunds("достигнут бюджет автоматических переделок")
        oid = str(uuid4())
        s.add(BillingOperation(id=oid, client_id=c.id, project_id=p.id, job_id=jid, run_id=job.run_id,
            kind=kind, model=model or "", reserved_rub=amount, markup=markup_of(c, org) if c.billing else 1,
            billable=c.billing, is_retry=retry_context.get(), status="reserved"))
        return oid


def submitted(task_id=""):
    oid = operation_context.get()
    if oid:
        with db.session() as s:
            op = s.get(BillingOperation, oid, with_for_update=True)
            op.status = "submitted"
            if task_id:
                op.external_id = str(task_id)


def settle(oid, cost, tokens=None, provider=""):
    if not oid:
        return
    cost = Decimal(str(cost or 0))
    if not cost.is_finite() or cost < 0:
        raise ValueError("некорректная стоимость провайдера")
    cost = cost.quantize(Decimal("0.0001"))
    with db.session() as s:
        snap = s.get(BillingOperation, oid)
        c = s.get(Client, snap.client_id, with_for_update=True)
        op = s.get(BillingOperation, oid, with_for_update=True, populate_existing=True)
        if op.status == "settled":
            return
        amount = money(cost * Decimal(str(op.markup)))
        if op.billable:
            c.balance_rub = money(c.balance_rub) - amount
            s.add(BalanceEntry(client_id=c.id, project_id=op.project_id, kind="charge", amount_rub=-amount,
                cost_rub=cost, balance_after=c.balance_rub, what=op.kind, ref=oid))
        job = s.get(Job, op.job_id) if op.job_id else None
        s.add(UsageEntry(org_id=c.org_id, project_id=op.project_id, product_id=job.product_id if job else None,
            frame_id=job.frame_id if job else None, kind=op.kind, model=op.model, provider=provider,
            amount_rub=cost, tokens=tokens or {}, ref=oid))
        op.status, op.cost_rub, op.charged_rub = "settled", cost, amount


def release(oid, uncertain=False):
    if oid:
        with db.session() as s:
            op = s.get(BillingOperation, oid, with_for_update=True)
            if op.status != "settled":
                op.status = "uncertain" if uncertain or op.status == "submitted" else "released"


def invoke(kind, model, fn, trace=None):
    oid = reserve(kind, model)
    token = operation_context.set(oid)
    before = len(trace.usage) if trace else 0
    try:
        result = fn()
        if trace:
            usage = trace.usage[before:]
            settle(oid, sum(x["cost"] for x in usage), usage[-1]["tokens"] if usage else {})
        else:
            from ..ai.polza import cost_of
            settle(oid, cost_of(result), provider=result.get("provider", ""))
            result["_billing_operation"] = oid
        return result
    except Exception as e:
        usage = trace.usage[before:] if trace else []
        if usage:
            settle(oid, sum(x["cost"] for x in usage), usage[-1]["tokens"])
        elif type(e).__name__ == "TaskFailed":
            from ..ai.polza import cost_of
            settle(oid, cost_of(e.data))
        else:
            release(oid)
        raise
    finally:
        operation_context.reset(token)


def not_charged():
    """Provider explicitly rejected the request, or transport proved it was never sent."""
    oid = operation_context.get()
    if oid:
        with db.session() as s:
            op = s.get(BillingOperation, oid, with_for_update=True)
            if op.status != "settled":
                op.status = "released"
