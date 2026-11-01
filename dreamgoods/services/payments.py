"""Резерв и однократное списание для каждого платного вызова."""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
from sqlalchemy import func,select
from .. import db
from ..core.money import decimal,money
from ..db.models import PaidOperation,BudgetBatch,Client,Project,Organization,Job,UsageEntry,BalanceEntry

job_context=ContextVar('paid_job',default=None)
batch_context=ContextVar('paid_batch',default=None)
operation_context=ContextVar('paid_operation',default=None)
retry_context=ContextVar('paid_retry',default=False)
HELD=('reserved','submitted','uncertain')

class BudgetPause(ValueError):
    status=402


def held(s,client_id):
    return money(s.scalar(select(func.coalesce(func.sum(PaidOperation.reserved_rub),0)).where(
        PaidOperation.client_id==client_id,PaidOperation.billable.is_(True),PaidOperation.status.in_(HELD))))


def estimate_call(s,org_id,model,kind):
    samples=s.scalars(select(UsageEntry.amount_rub).where(UsageEntry.org_id==org_id,UsageEntry.model==model,
        UsageEntry.kind==kind,UsageEntry.amount_rub>0).order_by(UsageEntry.id.desc()).limit(100)).all()
    st=s.get(Organization,org_id).settings or {}
    image=kind in ('generation','edit','persona_image')
    configured=st.get('reserve_image_rub' if image else 'reserve_chat_rub')
    fallback=decimal(configured if configured is not None else 50 if image else 5)
    fallback=max(decimal('0.01'),fallback)
    mean=sum((decimal(x) for x in samples),decimal(0))/len(samples) if samples else fallback
    upper=max((decimal(x) for x in samples),default=fallback)*decimal('1.25')
    if configured is not None:upper=max(fallback,upper)
    return money(mean),money(upper),len(samples)


def _usage(s,batch_id):
    rows=s.scalars(select(PaidOperation).where(PaidOperation.batch_id==batch_id,PaidOperation.status!='released')).all()
    total=sum((decimal(o.charged_rub if o.status=='settled' else o.reserved_rub) for o in rows),decimal(0))
    retries=sum((decimal(o.charged_rub if o.status=='settled' else o.reserved_rub) for o in rows if o.is_retry),decimal(0))
    return total,retries


def reserve(kind,model,trace=None):
    from .billing import markup_of
    jid=job_context.get() or getattr(trace,'job_id',None)
    if not jid:return None
    denied=None
    with db.session() as s:
        j=s.get(Job,jid)
        if not j or not j.project_id:return None
        p=s.get(Project,j.project_id)
        c=s.get(Client,p.client_id,with_for_update=True,populate_existing=True)
        batch=s.get(BudgetBatch,j.batch_id,with_for_update=True) if j.batch_id else None
        if kind=='generation':
            kind='persona_image' if j.kind=='persona' else 'edit' if (j.payload or {}).get('edit') else kind
        billable=c.billing and not bool((j.payload or {}).get('by_master'))
        markup=markup_of(c,s.get(Organization,c.org_id)) if billable else 1
        _,upper,_=estimate_call(s,c.org_id,model,kind)
        amount=money(decimal(upper)*decimal(markup))
        retry=retry_context.get() or bool((j.payload or {}).get('budget_retry'))
        if batch and batch.state=='paused':denied=batch.pause_reason or 'Партия приостановлена'
        elif billable and decimal(c.balance_rub)-decimal(held(s,c.id))<decimal(amount):denied=f'Недостаточно доступного баланса для резерва {amount:.2f} ₽'
        if batch and not denied:
            total,retries=_usage(s,batch.id)
            if batch.budget_rub is not None and total+decimal(amount)>decimal(batch.budget_rub):denied='Достигнут общий бюджет партии'
            elif retry and batch.retry_budget_rub is not None and retries+decimal(amount)>decimal(batch.retry_budget_rub):denied='Достигнут бюджет автоматических переделок'
        if denied:
            if batch:batch.state,batch.pause_reason='paused',denied
        else:
            oid=str(uuid4())
            s.add(PaidOperation(id=oid,client_id=c.id,project_id=p.id,job_id=j.id,batch_id=j.batch_id,
                product_id=j.product_id,frame_id=j.frame_id,kind=kind,model=model or '',reserved_rub=amount,
                markup=markup,billable=billable,is_retry=retry))
    if denied:raise BudgetPause(denied)
    return oid


def submitted(external_id=''):
    oid=operation_context.get()
    if oid:
        with db.session() as s:
            o=s.get(PaidOperation,oid,with_for_update=True)
            if o.status=='released':raise BudgetPause('Резерв уже снят. Запрос не отправлен.')
            if o.status=='settled':return
            o.status='submitted'
            if external_id:o.external_id=str(external_id)


def not_charged():
    oid=operation_context.get()
    if oid:release(oid,known=True)


def release(oid,known=False):
    if oid:
        with db.session() as s:
            snapshot=s.get(PaidOperation,oid)
            if not snapshot:return
            s.get(Client,snapshot.client_id,with_for_update=True)
            batch=s.get(BudgetBatch,snapshot.batch_id,with_for_update=True) if snapshot.batch_id else None
            o=s.get(PaidOperation,oid,with_for_update=True,populate_existing=True)
            if o and o.status not in ('settled','released'):
                o.status='released' if known or o.status=='reserved' else 'uncertain'
                if o.status=='uncertain' and batch:
                    batch.state,batch.pause_reason='paused','Статус запроса неизвестен. Резерв сохранён до сверки с провайдером.'


def settle(oid,cost,tokens=None,provider=''):
    if not oid:return
    cost=decimal(cost or 0)
    if cost<0:raise ValueError('Отрицательная стоимость провайдера')
    cost=money(cost,6)
    with db.session() as s:
        snap=s.get(PaidOperation,oid)
        if not snap:raise LookupError('Платёжная операция не найдена')
        c=s.get(Client,snap.client_id,with_for_update=True,populate_existing=True)
        batch=s.get(BudgetBatch,snap.batch_id,with_for_update=True) if snap.batch_id else None
        o=s.get(PaidOperation,oid,with_for_update=True,populate_existing=True)
        if o.status=='settled':return
        amount=money(decimal(cost)*decimal(o.markup))
        if o.billable and amount:
            c.balance_rub=money(decimal(c.balance_rub)-decimal(amount))
            s.add(BalanceEntry(client_id=c.id,project_id=o.project_id,kind='charge',amount_rub=-amount,
                cost_rub=cost,balance_after=c.balance_rub,what=o.kind,ref=o.id))
        s.add(UsageEntry(org_id=c.org_id,project_id=o.project_id,product_id=o.product_id,frame_id=o.frame_id,
            kind=o.kind,model=o.model,provider=provider,amount_rub=cost,tokens=tokens or {},ref=o.id))
        o.status,o.cost_rub,o.charged_rub='settled',cost,amount
        s.flush()
        if batch:
            total,retries=_usage(s,batch.id)
            if (batch.budget_rub is not None and total>decimal(batch.budget_rub) or
                batch.retry_budget_rub is not None and retries>decimal(batch.retry_budget_rub)):
                batch.state,batch.pause_reason='paused','Фактическая стоимость превысила бюджет. Новые запросы остановлены.'
        if amount>o.reserved_rub and batch:
            batch.state,batch.pause_reason='paused','Цена провайдера оказалась выше резерва. Проверьте расходы перед продолжением.'


@contextmanager
def call(kind,model,trace=None):
    oid=reserve(kind,model,trace)
    token=operation_context.set(oid)
    try:
        yield oid
    except Exception as e:
        if type(e).__name__=='TaskFailed' and oid:
            from ..ai.polza import cost_of
            settle(oid,cost_of(e.data))
        else:release(oid)
        raise
    finally:
        operation_context.reset(token)
