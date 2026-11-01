from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import requests
from sqlalchemy import func,select
from dreamgoods import db
from dreamgoods.ai import polza
from dreamgoods.core.logs import Trace
from dreamgoods.db.models import BudgetBatch,PaidOperation,Client,Job,Generation,BalanceEntry,UsageEntry,Organization
from dreamgoods.services import budgets,payments,billing
from dreamgoods.services.common import write_usage
from dreamgoods.workers import queue


def make_job(ids,budget=None,retries=None,master=False):
    with db.session() as s:
        b=budgets.new_batch(s,ids['project'],budget,retries)
        j=Job(project_id=ids['project'],product_id=ids['product'],frame_id=ids['frame'],kind='generate',batch_id=b.id,payload={'by_master':master})
        s.add(j);s.flush();return j.id,b.id

@contextmanager
def scope(jid,retry=False):
    a=payments.job_context.set(jid);b=payments.retry_context.set(retry)
    try:yield
    finally:payments.retry_context.reset(b);payments.job_context.reset(a)


def test_reserve_reduces_available_balance(database):
    _,ids=database;jid,bid=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==200
        assert payments.held(s,ids['client'])==62.5
    data=budgets.listing(ids['project'])
    assert data['reserved']==62.5 and data['available']==137.5
    assert data['batches'][0]['reserved']==62.5


def test_settle_once_and_release_unused_reserve(database):
    _,ids=database;jid,bid=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,10);payments.settle(oid,99)
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==190
        assert payments.held(s,ids['client'])==0
        assert s.scalar(select(func.count(BalanceEntry.id)))==1
        assert s.scalar(select(func.count(UsageEntry.id)))==1
    assert budgets.listing(ids['project'])['batches'][0]['spent']==10


def test_reserved_and_uncertain_are_released_differently(database):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.release(oid)
    with db.session() as s:assert s.get(PaidOperation,oid).status=='released'
    with scope(jid):
        oid=payments.reserve('generation','fake');t=payments.operation_context.set(oid)
        try:payments.submitted('external-task')
        finally:payments.operation_context.reset(t)
    payments.release(oid)
    with db.session() as s:
        assert s.get(PaidOperation,oid).status=='uncertain'
        assert payments.held(s,ids['client'])==62.5
    payments.release(oid,known=True)
    with db.session() as s:assert payments.held(s,ids['client'])==0


def test_total_budget_pauses_before_second_request(database):
    _,ids=database;jid,bid=make_job(ids,budget=100)
    with scope(jid):
        oid=payments.reserve('generation','fake')
        with pytest.raises(payments.BudgetPause,match='общий бюджет'):payments.reserve('generation','fake')
    with db.session() as s:
        assert s.get(BudgetBatch,bid).state=='paused'
        assert s.scalar(select(func.count(PaidOperation.id)))==1
    payments.settle(oid,10)
    budgets.resume(ids['project'],bid,100,None)
    with scope(jid):assert payments.reserve('generation','fake')


def test_zero_retry_budget_blocks_paid_retry(database):
    _,ids=database;jid,bid=make_job(ids,budget=100,retries=0)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,5)
    with scope(jid,retry=True):
        with pytest.raises(payments.BudgetPause,match='переделок'):payments.reserve('generation','fake')
    assert budgets.listing(ids['project'])['batches'][0]['state']=='paused'


def test_master_does_not_debit_client(database):
    _,ids=database;jid,bid=make_job(ids,master=True)
    with db.session() as s:s.get(Client,ids['client']).balance_rub=0
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,10)
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==0
        assert payments.held(s,ids['client'])==0
        assert s.scalar(select(func.count(BalanceEntry.id)))==0
        assert s.scalar(select(func.count(UsageEntry.id)))==1


def test_price_above_reserve_pauses_batch(database):
    _,ids=database;jid,bid=make_job(ids,budget=1000)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,80)
    report=budgets.listing(ids['project'])['batches'][0]
    assert report['spent']==80 and report['state']=='paused'
    assert 'выше резерва' in report['pause_reason']


def test_known_reject_does_not_hold_money(database):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):
        with payments.call('generation','fake') as oid:
            payments.submitted();payments.not_charged()
    with db.session() as s:assert s.get(PaidOperation,oid).status=='released'


def test_failed_chat_keeps_reserve_and_is_not_retried(database,monkeypatch):
    _,ids=database;jid,_=make_job(ids)
    post=Mock(side_effect=requests.ReadTimeout('unknown charge'))
    monkeypatch.setattr(polza.http,'post',post)
    monkeypatch.setattr(polza,'qc_endpoint',lambda st:('https://fake','fake'))
    monkeypatch.setattr(polza.throttle,'limiter',lambda *a:Mock())
    with scope(jid):
        with pytest.raises(RuntimeError):polza.chat({},'fake','','',Trace('test'),'сверка')
    with db.session() as s:
        assert s.scalar(select(PaidOperation)).status=='uncertain'
        assert payments.held(s,ids['client'])==6.25
    assert post.call_count==1


def test_chat_settles_before_json_error_and_repair_obeys_retry_budget(database,monkeypatch):
    _,ids=database;jid,_=make_job(ids,retries=0)
    response=SimpleNamespace(status_code=200,text='',json=lambda:{'choices':[{'message':{'content':'bad json'}}],'usage':{'cost_rub':1}})
    post=Mock(return_value=response)
    monkeypatch.setattr(polza.http,'post',post)
    monkeypatch.setattr(polza,'qc_endpoint',lambda st:('https://fake','fake'))
    monkeypatch.setattr(polza.throttle,'limiter',lambda *a:Mock())
    with scope(jid):
        with pytest.raises(payments.BudgetPause):polza.chat({},'fake','','',Trace('test'),'сверка')
    assert post.call_count==1
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==199
        assert s.scalar(select(func.count(UsageEntry.id)))==1


def test_managed_usage_is_not_charged_again(database):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,10)
    trace=Trace('test');trace.add('generation','fake',10,paid_operation=oid)
    with db.session() as s:write_usage(s,ids['org'],ids['project'],ids['product'],ids['frame'],trace)
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==190
        assert s.scalar(select(func.count(UsageEntry.id)))==1


def test_new_job_inherits_batch_scope(database):
    _,ids=database
    with budgets.launch(ids['project'],100,20) as batch:
        with db.session() as s:j=queue.enqueue(s,'generate',ids['project'],frame_id=ids['frame'])
    assert j.batch_id==batch.id


def test_resume_does_not_duplicate_paused_frame(database):
    _,ids=database;jid,bid=make_job(ids)
    with db.session() as s:s.get(Job,jid).status='paused';s.get(BudgetBatch,bid).state='paused'
    with db.session() as s:assert queue.enqueue(s,'generate',ids['project'],frame_id=ids['frame']) is None
    budgets.resume(ids['project'],bid,None,None)
    with db.session() as s:assert s.get(Job,jid).status=='queued'


def test_estimate_has_fallback_and_counts_prepared_frames(database):
    _,ids=database
    from dreamgoods.db.models import ProductProfile,Product
    with db.session() as s:
        p=ProductProfile(product_id=ids['product'],version=1,data={});s.add(p);s.flush()
        s.get(Product,ids['product']).current_profile_id=p.id
    result=budgets.quote(ids['project'],frame_ids=[ids['frame']])
    assert result['frames']==1 and result['base_estimate']>0
    assert result['reserve_upper']>=result['base_estimate']
    assert result['historical_samples']==0


def test_resume_rejects_limit_below_spent(database):
    _,ids=database;jid,bid=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,10)
    with pytest.raises(ValueError):budgets.resume(ids['project'],bid,5,None)


def test_child_thread_uses_trace_job_identity(database,monkeypatch):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):trace=Trace('import')
    with ThreadPoolExecutor(max_workers=1) as pool:
        oid=pool.submit(payments.reserve,'sort','fake',trace).result()
    assert oid
    with db.session() as s:assert s.get(PaidOperation,oid).job_id==jid


@pytest.mark.postgres
def test_concurrent_reservations_cannot_spend_same_balance(database):
    engine,ids=database
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL required')
    jid,_=make_job(ids)
    with db.session() as s:s.get(Client,ids['client']).balance_rub=100
    def reserve(_):
        with scope(jid):
            try:return payments.reserve('generation','fake')
            except payments.BudgetPause:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,range(2)))
    assert sum(x is not None for x in results)==1
    with db.session() as s:assert payments.held(s,ids['client'])==62.5


@pytest.mark.postgres
def test_concurrent_settlement_is_once(database):
    engine,ids=database
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL required')
    jid,_=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:payments.settle(oid,10),range(2)))
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==190
        assert s.scalar(select(func.count(UsageEntry.id)))==1


@pytest.mark.postgres
def test_paused_batch_is_not_claimed(database):
    engine,ids=database
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL required')
    jid,bid=make_job(ids)
    with db.session() as s:s.get(BudgetBatch,bid).state='paused'
    assert queue._claim('test') is None


def test_unknown_submission_pauses_batch(database):
    _,ids=database;jid,bid=make_job(ids)
    with scope(jid):
        with pytest.raises(RuntimeError):
            with payments.call('generation','fake'):
                payments.submitted('task')
                raise RuntimeError('lost response')
    with db.session() as s:assert s.get(BudgetBatch,bid).state=='paused'


def test_recovery_keeps_submitted_hold_and_releases_unsent(database):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):
        unused=payments.reserve('generation','fake')
        sent=payments.reserve('qc','fake')
        t=payments.operation_context.set(sent)
        try:payments.submitted('task')
        finally:payments.operation_context.reset(t)
    with db.session() as s:
        j=s.get(Job,jid);j.status='running';j.worker='dead-process/worker-1'
    queue.recover()
    with db.session() as s:
        assert s.get(PaidOperation,unused).status=='released'
        assert s.get(PaidOperation,sent).status=='uncertain'


def test_released_operation_cannot_be_sent(database):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.release(oid,known=True)
    t=payments.operation_context.set(oid)
    try:
        with pytest.raises(payments.BudgetPause):payments.submitted()
    finally:payments.operation_context.reset(t)


def test_budget_router_denies_non_master_reconciliation(database):
    _,ids=database;jid,_=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    from dreamgoods.api.routers.budgets import reconcile,Reconcile
    from dreamgoods.core.auth import CurrentUser,Forbidden
    user=CurrentUser(1,ids['org'],'user','User','user',ids['client'])
    request=SimpleNamespace(state=SimpleNamespace(user=user))
    with pytest.raises(Forbidden):reconcile(oid,Reconcile(action='release',note='checked no charge'),request,pid=ids['project'])


def test_budget_paused_qc_is_deferred_without_new_image(database):
    _,ids=database;jid,bid=make_job(ids)
    with db.session() as s:
        g=Generation(frame_id=ids['frame'],job_id=jid,status='ok');s.add(g);s.flush()
        from dreamgoods.db.models import Frame
        f=s.get(Frame,ids['frame']);f.current_generation_id=g.id;f.status='unchecked'
        j=s.get(Job,jid);j.payload={'deferred_budget_check':True}
        s.get(BudgetBatch,bid).state='paused'
    queue._finish(jid,'done')
    with db.session() as s:
        jobs=s.scalars(select(Job).order_by(Job.id)).all()
        assert len(jobs)==2 and jobs[0].status=='done' and jobs[1].kind=='check'
        assert jobs[1].batch_id==bid and jobs[1].status=='queued'
        assert s.scalar(select(func.count(Generation.id)))==1


def test_image_call_persists_operation_before_task_callback(database,monkeypatch):
    _,ids=database;jid,_=make_job(ids)
    monkeypatch.setattr(polza,'_submit',lambda *a:{'id':'task','status':'completed','usage':{'cost_rub':10}})
    captured=[]
    def on_task(task):
        oid=payments.operation_context.get()
        with db.session() as s:
            assert s.get(PaidOperation,oid).external_id==task
        captured.append(oid)
    with scope(jid):
        data=polza._generate_once({'model':'fake','aspect':'3:4','resolution':'2K'},'fake','prompt',[],on_task=on_task)
    assert data['_paid_operation']==captured[0]
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==190
        assert s.get(PaidOperation,captured[0]).status=='settled'


@pytest.mark.postgres
def test_recovered_result_uses_existing_paid_operation(database,monkeypatch,tmp_path):
    engine,ids=database
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL required')
    from dreamgoods.workers import resume
    from dreamgoods.db.models import Project
    from dreamgoods.core import storage
    from PIL import Image
    import io
    jid,_=make_job(ids)
    with scope(jid):oid=payments.reserve('generation','fake')
    payments.settle(oid,10)
    with db.session() as s:
        s.get(Job,jid).status='done'
        s.get(Project,ids['project']).settings={'qc_enabled':False}
        g=Generation(frame_id=ids['frame'],job_id=jid,model='fake',status='pending',external_id='task',paid_operation_id=oid)
        s.add(g);s.flush();gid,created=g.id,g.created_at
    monkeypatch.setattr(storage.config,'STORAGE_DIR',tmp_path)
    monkeypatch.setattr(polza,'get_task',lambda *a,**k:{'status':'completed','usage':{'cost_rub':10}})
    buf=io.BytesIO();Image.new('RGB',(64,64),'white').save(buf,'PNG')
    monkeypatch.setattr(polza,'extract_image',lambda data:buf.getvalue())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:resume._resume(gid,created),range(2)))==[0,1]
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub==190
        assert s.scalar(select(func.count(UsageEntry.id)))==1
        assert s.scalar(select(func.count(BalanceEntry.id)))==1
