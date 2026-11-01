"""Партии: смета, пауза/продолжение и отчёт по артикулам."""
from contextlib import contextmanager
from sqlalchemy import func,select
from .. import db
from ..core import presets as P
from ..core.money import decimal,money
from ..db.models import BudgetBatch,PaidOperation,Client,Project,Product,Frame,Job,Generation,UsageEntry
from . import payments,billing
from .common import context


def new_batch(s,pid,budget=None,retry_budget=None,title='Генерация'):
    for value in (budget,retry_budget):
        if value is not None and (decimal(value)<0 or decimal(value)>decimal('1000000000')):raise ValueError('Недопустимый бюджет')
    b=BudgetBatch(project_id=pid,title=title,budget_rub=money(budget) if budget is not None else None,
                  retry_budget_rub=money(retry_budget) if retry_budget is not None else None)
    s.add(b);s.flush();return b


@contextmanager
def launch(pid,budget=None,retry_budget=None,title='Генерация'):
    with db.session() as s:b=new_batch(s,pid,budget,retry_budget,title)
    token=payments.batch_context.set(b.id)
    try:yield b
    finally:payments.batch_context.reset(token)


def quote(pid,product_ids=None,frame_ids=None,limit=0,count=None):
    with db.session() as s:
        project=s.get(Project,pid);client=s.get(Client,project.client_id)
        q=select(Product).where(Product.project_id==pid).order_by(Product.id)
        if product_ids is not None:q=q.where(Product.id.in_(product_ids))
        if frame_ids is not None:q=q.where(Product.id.in_(select(Frame.product_id).where(Frame.id.in_(frame_ids))))
        products=s.scalars(q).all()
        base=retry=upper=0;frames_count=profiles=historical=0
        for p in products:
            _,org,st=context(s,p)
            markup=billing.markup_of(client,org) if client.billing and not billing.by_master.get() else 1
            fs=s.scalars(select(Frame).where(Frame.product_id==p.id,Frame.status!='retired').order_by(Frame.position)).all()
            planned_count=len(fs)
            if frame_ids is not None:fs=[f for f in fs if f.id in frame_ids]
            else:fs=[f for f in fs if not f.current_generation_id]
            n=len(fs)
            if count and frame_ids is None:
                n=max(n,min(planned_count,max(0,count-frames_count)))
            if not p.current_profile_id and frame_ids is None:
                profiles+=1;n=max(n,P.total(P.plan_of(st)))
                mean,cap,samples=payments.estimate_call(s,org.id,st.get('profile_model',''),'profile')
                base+=mean*markup;upper+=cap*markup;historical+=samples
            if limit:n=min(n,max(0,limit-frames_count))
            if count is not None:n=min(n,max(0,count-frames_count)) if count else n
            if not n:continue
            frames_count+=n
            attempts=0 if not st.get('qc_enabled') or not st.get('qc_autoregen') else max(0,int(st.get('qc_retries') or 0))
            image_model=st.get('model','')
            mean,cap,samples=payments.estimate_call(s,org.id,image_model,'generation')
            frame_mean,frame_cap=mean,cap;historical+=samples
            if st.get('qc_enabled'):
                for kind in ['qc']+(['spec','count'] if st.get('qc_count') else []):
                    qm=st.get('qc_count_model') or st.get('qc_model','') if kind in ('count','spec') else st.get('qc_model','')
                    avg,maxprice,samples=payments.estimate_call(s,org.id,qm,kind)
                    frame_mean+=avg;frame_cap+=maxprice;historical+=samples
                avg,maxprice,samples=payments.estimate_call(s,org.id,st.get('qc_model',''),'views')
                base+=avg*markup;upper+=maxprice*markup;historical+=samples
            base+=frame_mean*n*markup
            retry+=frame_mean*n*attempts*markup
            upper+=frame_cap*n*(1+attempts)*markup
        return dict(frames=frames_count,profiles=profiles,base_estimate=money(base),retry_estimate=money(retry),
                    reserve_upper=money(upper),historical_samples=historical,
                    unit='клиентская цена' if client.billing and not billing.by_master.get() else 'себестоимость',
                    note='Оценка по истории модели; без истории — 50 ₽ за изображение и 5 ₽ за текстовый вызов, для резерва добавляется запас 25%. Цена провайдера может отличаться.')


def view(s,b):
    ops=s.scalars(select(PaidOperation).where(PaidOperation.batch_id==b.id)).all()
    jobs=s.scalars(select(Job).where(Job.batch_id==b.id)).all()
    spent=money(sum(decimal(o.charged_rub) for o in ops if o.status=='settled'))
    held=money(sum(decimal(o.reserved_rub) for o in ops if o.status in payments.HELD))
    retries=money(sum(decimal(o.charged_rub) for o in ops if o.status=='settled' and o.is_retry))
    state=b.state
    if state=='active' and not held and not any(j.status in ('queued','running','cancelling','paused') for j in jobs):state='done'
    pids={o.product_id for o in ops if o.product_id}
    names=dict(s.execute(select(Product.id,Product.sku).where(Product.id.in_(pids))).all()) if pids else {}
    accepted=dict(s.execute(select(Frame.product_id,func.count(Frame.id)).join(Generation,Generation.id==Frame.current_generation_id)
        .join(Job,Job.id==Generation.job_id).where(Job.batch_id==b.id,Frame.status.in_(('accepted','pass')))
        .group_by(Frame.product_id)).all())
    reports=[]
    for pid in sorted({o.product_id for o in ops},key=lambda x:x or 0):
        rows=[o for o in ops if o.product_id==pid]
        product_spent=money(sum(decimal(o.charged_rub) for o in rows if o.status=='settled'))
        reports.append(dict(product_id=pid,sku=names.get(pid,'Подготовка партии'),
            spent=money(sum(decimal(o.charged_rub) for o in rows if o.status=='settled')),
            reserved=money(sum(decimal(o.reserved_rub) for o in rows if o.status in payments.HELD)),
            retries=money(sum(decimal(o.charged_rub) for o in rows if o.status=='settled' and o.is_retry)),
            accepted=accepted.get(pid,0),cost_per_accepted=money(product_spent/accepted[pid]) if accepted.get(pid) else None))
    unit='клиентская цена' if any(o.billable for o in ops) or (not ops and jobs and not (jobs[0].payload or {}).get('by_master')) else 'себестоимость'
    return dict(id=b.id,title=b.title,unit=unit,created=b.created_at.isoformat(),state=state,pause_reason=b.pause_reason,
        budget=b.budget_rub,retry_budget=b.retry_budget_rub,spent=spent,reserved=held,retries=retries,
        queued=sum(j.status=='queued' for j in jobs),running=sum(j.status in ('running','cancelling') for j in jobs),
        paused=sum(j.status=='paused' for j in jobs),products=reports)


def listing(pid,admin=False):
    with db.session() as s:
        p=s.get(Project,pid);c=s.get(Client,p.client_id)
        batches=s.scalars(select(BudgetBatch).where(BudgetBatch.project_id==pid).order_by(BudgetBatch.id.desc()).limit(30)).all()
        ops=s.scalars(select(PaidOperation).where(PaidOperation.project_id==pid,PaidOperation.status.in_(payments.HELD))
                      .order_by(PaidOperation.created_at.desc()).limit(100)).all()
        reserved=payments.held(s,c.id)
        unresolved=[dict(id=o.id,kind=o.kind,model=o.model,status=o.status,reserved=o.reserved_rub,
                        external_id=o.external_id if admin else '',job_id=o.job_id,note=o.note) for o in ops]
        return dict(batches=[view(s,b) for b in batches],balance=money(c.balance_rub),reserved=reserved,
            available=money(decimal(c.balance_rub)-decimal(reserved)),operations=unresolved,admin=admin,
            paused_jobs=s.scalar(select(func.count(Job.id)).where(Job.project_id==pid,Job.batch_id.is_(None),Job.status=='paused')))


def resume(pid,batch_id,budget,retry_budget):
    with db.session() as s:
        b=s.get(BudgetBatch,batch_id,with_for_update=True)
        if not b or b.project_id!=pid:raise LookupError('Партия не найдена')
        spent,retries=payments._usage(s,b.id)
        for value,used in ((budget,spent),(retry_budget,retries)):
            if value is not None and decimal(value)<used:raise ValueError('Новый лимит меньше уже потраченного и зарезервированного')
        b.budget_rub=money(budget) if budget is not None else None
        b.retry_budget_rub=money(retry_budget) if retry_budget is not None else None
        b.state,b.pause_reason='active',''
        jobs=s.scalars(select(Job).where(Job.batch_id==b.id,Job.status=='paused').order_by(Job.id).with_for_update()).all()
        for j in jobs:
            pending=s.scalar(select(Generation.id).where(Generation.frame_id==j.frame_id,Generation.status=='pending').limit(1)) if j.frame_id else None
            if not pending:j.status,j.error,j.finished_at='queued','',None
    from ..workers.queue import _wake
    _wake.set()
    return {'ok':True}
