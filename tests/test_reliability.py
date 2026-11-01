from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select, func
from fastapi.testclient import TestClient

from dreamgoods import db
from dreamgoods.ai import qc, polza
from dreamgoods.core import auth, storage
from dreamgoods.core.logs import Trace
from dreamgoods.db.models import (BillingOperation, BalanceEntry, Client, Frame, Generation, GenerationRun,
    Job, Product, Project, QCCheck, UsageEntry)
from dreamgoods.services import payments, billing, board, frames, estimates, review_board, backups, export
from dreamgoods.workers import queue, resume


def job(ids, run_id=None):
    with db.session() as s:
        j = Job(project_id=ids['project'], product_id=ids['product'], frame_id=ids['frame'],
            kind='generate', status='running', run_id=run_id)
        s.add(j); s.flush(); return j.id

@pytest.mark.parametrize('response', [{}, {'defects':None}, {'defects':'ok'}, {'defects':[2]}, {'defects':['']}, {'defects':[{'text':'bad'}]}])
def test_invalid_qc_never_passes(response):
    with pytest.raises(ValueError): qc.validated_defects(response)

def test_qc_valid_and_critical_weight(monkeypatch):
    assert qc.validated_defects({'defects':[]}) == []
    assert qc.validated_defects({'defects':['wrong shape']})[0]['severity'] == 'major'
    monkeypatch.setattr(qc, 'tech_check', lambda *a: ([], {}))
    monkeypatch.setattr(qc, 'vlm_check', lambda *a: {'cost':1, 'reasons':['broken'],
        'defects':[{'text':'broken','category':'identity','severity':'critical'}]})
    result = qc.run_qc({}, '', [], b'', Trace('test'))
    assert not result['pass'] and result['info']['weighted_penalty'] == 100


def test_reservation_settlement_is_once(database):
    _, ids = database
    token = payments.job_context.set(job(ids))
    try:
        oid = payments.reserve('generation','test')
        with db.session() as s:
            assert payments.held(s, ids['client']) > 0
        payments.settle(oid, Decimal('12.3456'))
        payments.settle(oid, 99)
        with db.session() as s:
            assert payments.money(s.get(Client,ids['client']).balance_rub) == Decimal('187.65')
            assert s.scalar(select(func.count(BalanceEntry.id))) == 1
            assert s.scalar(select(func.count(UsageEntry.id))) == 1
            assert payments.held(s, ids['client']) == 0
            assert s.get(BillingOperation, oid).cost_rub == pytest.approx(12.3456)
    finally: payments.job_context.reset(token)


def test_reserve_blocks_low_balance_and_budget(database):
    _, ids = database
    with db.session() as s:
        c = s.get(Client,ids['client']); c.balance_rub=1
    t=payments.job_context.set(job(ids))
    try:
        with pytest.raises(billing.NoFunds): payments.reserve('generation','test')
    finally: payments.job_context.reset(t)
    with db.session() as s:
        s.get(Client,ids['client']).balance_rub=200
        old=s.scalar(select(Job)); old.status='done'
        batch=GenerationRun(project_id=ids['project'],budget_rub=100,retry_budget_rub=0)
        s.add(batch);s.flush();rid=batch.id
    t=payments.job_context.set(job(ids,rid)); rt=payments.retry_context.set(True)
    try:
        with pytest.raises(billing.NoFunds,match='переделок'): payments.reserve('generation','test')
    finally: payments.job_context.reset(t);payments.retry_context.reset(rt)


def test_invalid_paid_response_still_accounted_and_no_double_charge(database):
    _,ids=database
    t=payments.job_context.set(job(ids)); trace=Trace('test')
    def paid_invalid():
        payments.submitted()
        trace.add('qc','test',1.23)
        raise ValueError('bad json')
    try:
        with pytest.raises(ValueError): payments.invoke('qc','test',paid_invalid,trace)
        with db.session() as s:
            from dreamgoods.services.common import write_usage
            write_usage(s,ids['org'],ids['project'],ids['product'],ids['frame'],trace)
        with db.session() as s:
            assert s.scalar(select(func.count(UsageEntry.id))) == 1
            assert s.scalar(select(func.count(BalanceEntry.id))) == 1
    finally: payments.job_context.reset(t)


def test_ambiguous_timeout_keeps_reserve(database):
    _,ids=database;t=payments.job_context.set(job(ids))
    def timeout():
        payments.submitted('task-1'); raise TimeoutError()
    try:
        with pytest.raises(TimeoutError): payments.invoke('generation','test',timeout)
        with db.session() as s:
            op=s.scalar(select(BillingOperation))
            assert op.status=='uncertain' and op.external_id=='task-1'
            assert payments.held(s,ids['client']) > 0
    finally: payments.job_context.reset(t)


def test_catalog_pagination_search_global_counts_and_preview(database,monkeypatch):
    _,ids=database
    for i in range(5):
        with db.session() as s:
            s.add(Product(project_id=ids['project'],sku=f'NEW-{i}',name='Boots'))
    data=board.state(ids['project'],page=2,page_size=2)
    assert len(data['products'])==2 and data['pagination']['total']==6
    assert data['totals']['total']==1
    data=board.state(ids['project'],page_size=2,query='NEW-4')
    assert [x['sku'] for x in data['products']]==['NEW-4']
    assert board.progress(ids['project'])['version']
    estimate=estimates.preview(ids['project'],[ids['frame']])
    assert estimate['count']==1 and estimate['upper']>=estimate['expected']>0


def add_generation(ids):
    with db.session() as s:
        a=storage.put(s,ids['org'],png(),'output','test.png')
        g=Generation(frame_id=ids['frame'],model='test',status='ok',output_asset_id=a.id)
        s.add(g);s.flush()
        f=s.get(Frame,ids['frame']);f.current_generation_id=g.id;f.status='review'
        s.add(QCCheck(frame_id=f.id,generation_id=g.id,passed=False,info={'defects':[{'category':'identity','text':'color','severity':'major'}]},reasons=['color']))
        return g.id

def png():
    data=io.BytesIO();Image.new('RGB',(100,150),'red').save(data,'PNG');return data.getvalue()


def test_review_filter_stale_guard_and_scoping(database,monkeypatch,tmp_path):
    _,ids=database;monkeypatch.setattr(storage.config,'STORAGE_DIR',tmp_path)
    gid=add_generation(ids)
    listed=review_board.listing(ids['project'],defect='identity')
    assert len(listed['items'])==1
    with pytest.raises(ValueError,match='версия'): frames.review(ids['project'],ids['frame'],'ok','',False,expected_generation=gid+1)
    frames.review(ids['project'],ids['frame'],'ok','',False,expected_generation=gid)
    assert not review_board.listing(ids['project'])['items']


def test_export_format_and_integrity(database,monkeypatch,tmp_path):
    _,ids=database;monkeypatch.setattr(storage.config,'STORAGE_DIR',tmp_path/'files')
    monkeypatch.setattr(export.config,'EXPORT_DIR',tmp_path/'export')
    add_generation(ids)
    path,count=export.export_zip(ids['project'],include='all',output_format='jpeg')
    import zipfile
    with zipfile.ZipFile(path) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert count==1 and manifest[0]['file']=='SKU/01.jpg'
        with Image.open(io.BytesIO(z.read('SKU/01.jpg'))) as im:
            assert min(im.size)>=900 and abs(im.width/im.height-3/4)<.01
        assert manifest[0]['warnings']
    path,count=export.export_zip(ids['project'],include='all',require_complete=True)
    assert count==0


def test_backup_checksum_detects_corruption(tmp_path):
    p=tmp_path/'database.dump';p.write_bytes(b'backup')
    (tmp_path/'manifest.json').write_text(json.dumps({'checksums':{'database.dump':backups.sha_file(p)}}))
    backups.verify_checksums(tmp_path)
    p.write_bytes(b'broken')
    with pytest.raises(ValueError):backups.verify_checksums(tmp_path)


def test_api_user_cannot_read_other_project_or_review(database,monkeypatch):
    _,ids=database
    from dreamgoods.api.app import app
    u=auth.CurrentUser(id=1,org_id=ids['org'],email='test',name='test',role='user',client_id=ids['client'])
    monkeypatch.setattr(auth,'user_by_token',lambda t:u)
    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE,'test')
        assert c.get(f"/api/projects/{ids['project']}/state?page_size=2").status_code==200
        assert c.get('/api/admin/payments/pending').status_code==403
        assert c.get('/api/projects/999/review').status_code==404
        assert c.post(f"/api/projects/{ids['project']}/generate/preview",json={}).status_code==200
        assert c.get(f"/api/projects/{ids['project']}/state?page_size=999").status_code==422


@pytest.mark.postgres
def test_parallel_settlements_and_reservations(database):
    engine,ids=database
    if engine.dialect.name!='postgresql': pytest.skip('requires PostgreSQL row locks')
    jid=job(ids)
    def reserve():
        t=payments.job_context.set(jid)
        try:
            try:return payments.reserve('generation','test')
            except billing.NoFunds:return None
        finally:payments.job_context.reset(t)
    with ThreadPoolExecutor(max_workers=8) as pool: ops=[x for x in pool.map(lambda _:reserve(),range(8)) if x]
    assert len(ops)==3 # each hold 62.50, balance 200
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:payments.settle(ops[0],10),range(8)))
    with db.session() as s:
        assert s.scalar(select(func.count(BalanceEntry.id)))==1
        assert payments.money(s.get(Client,ids['client']).balance_rub)==Decimal('190')


@pytest.mark.postgres
def test_queue_duplicate_concurrent_and_client_fairness(database):
    engine,ids=database
    if engine.dialect.name!='postgresql':pytest.skip('requires PostgreSQL')
    def add():
        with db.session() as s:return bool(queue.enqueue(s,'generate',ids['project'],product_id=ids['product'],frame_id=ids['frame']))
    with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(lambda _:add(),range(6)))
    assert sum(results)==1
    assert queue._claim('test')
    # Another project belonging to the same client still shares its concurrency limit.
    with db.session() as s:
        s.get(Client,ids['client']).parallel_limit=1
        p=Project(client_id=ids['client'],name='Second');s.add(p);s.flush()
        queue.enqueue(s,'profile',p.id)
    assert queue._claim('test2') is None


def test_confirmed_rejection_releases_reserve(database):
    _,ids=database; t=payments.job_context.set(job(ids))
    def rejected():
        payments.submitted(); payments.not_charged(); raise ValueError("400 bad request")
    try:
        with pytest.raises(ValueError):payments.invoke("generation","test",rejected)
        with db.session() as s:assert payments.held(s,ids["client"]) == 0
    finally:payments.job_context.reset(t)


def test_incomplete_product_not_exported(database,monkeypatch,tmp_path):
    _,ids=database;monkeypatch.setattr(storage.config,"STORAGE_DIR",tmp_path/"files")
    monkeypatch.setattr(export.config,"EXPORT_DIR",tmp_path/"export")
    add_generation(ids)
    with db.session() as s:
        s.get(Frame,ids["frame"]).status="accepted"
        s.add(Frame(product_id=ids["product"],position=2,prompt="detail"))
    _,count=export.export_zip(ids["project"],require_complete=True)
    assert count == 0


@pytest.mark.postgres
def test_full_backup_restore(database,monkeypatch,tmp_path):
    engine,ids=database
    if engine.dialect.name != "postgresql":pytest.skip("requires PostgreSQL client tools and CREATEDB")
    monkeypatch.setattr(storage.config,"STORAGE_DIR",tmp_path/"files")
    monkeypatch.setenv("DREAMGOODS_BACKUP_DIR",str(tmp_path/"backups"))
    add_generation(ids)
    path=backups.create_backup(verify=True)
    assert (path/"database.dump").is_file()
    backups.verify_checksums(path)


def test_benchmark_requires_complete_predictions():
    from scripts.qc_benchmark import evaluate
    truth=[{"generation_id":1,"accepted":False},{"generation_id":2,"accepted":True}]
    result=evaluate(truth,[{"generation_id":1,"pass":True},{"generation_id":2,"pass":False}])
    assert result["missed_defects"]==1 and result["false_rejections"]==1
    with pytest.raises(ValueError):evaluate(truth,[])


@pytest.mark.postgres
def test_concurrent_resume_downloads_and_charges_once(database,monkeypatch,tmp_path):
    engine,ids=database
    if engine.dialect.name != "postgresql":pytest.skip("requires PostgreSQL locks")
    monkeypatch.setattr(storage.config,"STORAGE_DIR",tmp_path/"files")
    jid=job(ids); token=payments.job_context.set(jid)
    try:oid=payments.reserve("generation","test")
    finally:payments.job_context.reset(token)
    with db.session() as s:
        s.get(Job,jid).status="done"
        s.get(Project,ids["project"]).settings={"qc_enabled":False}
        g=Generation(frame_id=ids["frame"],job_id=jid,model="test",status="pending",external_id="task",billing_operation_id=oid)
        s.add(g);s.flush();gid,created=g.id,g.created_at
    monkeypatch.setattr(polza,"get_task",lambda *a,**k:{"id":"task","status":"completed","usage":{"cost_rub":10}})
    monkeypatch.setattr(polza,"extract_image",lambda data:png())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:resume._resume(gid,created),range(2)))
    assert sorted(results)==[0,1]
    with db.session() as s:
        assert s.get(Frame,ids["frame"]).current_generation_id==gid
        assert s.scalar(select(func.count(BalanceEntry.id)))==1
        assert s.scalar(select(func.count(UsageEntry.id)))==1
