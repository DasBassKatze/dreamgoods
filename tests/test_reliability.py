import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from dreamgoods import db
from dreamgoods.ai import polza, qc
from dreamgoods.core import auth, storage
from dreamgoods.core.events import utcnow
from dreamgoods.core.logs import Trace
from dreamgoods.core.money import money
from dreamgoods.db.models import (Asset, BalanceEntry, Client, EmailToken, Frame, Generation, Job,
                                 Organization, Product, Project, TopupRequest, UsageEntry, User)
from dreamgoods.services import access, billing, registration, topups
from dreamgoods.workers import queue, resume


@pytest.fixture(autouse=True)
def billing_context():
    token = billing.by_master.set(False)
    yield
    billing.by_master.reset(token)


def master(ids):
    return SimpleNamespace(id=None, org_id=ids['org'], master=True, client_id=None)


def request_id(ids, bonus=10):
    with db.session() as s:
        r = TopupRequest(client_id=ids['client'], amount_rub=100, bonus_rub=bonus)
        s.add(r); s.flush()
        return r.id


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', '1e100', 'not a number'])
def test_invalid_money(value):
    with pytest.raises(ValueError): money(value)


def test_money_rounds_half_up():
    assert money('1.005') == 1.01
    assert money('-1.005') == -1.01


def test_topup_is_atomic_and_cannot_be_repeated(database):
    _, ids = database
    rid = request_id(ids)
    topups.resolve(master(ids), rid, 'paid')
    with pytest.raises(ValueError): topups.resolve(master(ids), rid, 'paid')
    with db.session() as s:
        assert s.get(Client, ids['client']).balance_rub == 310
        assert s.scalar(select(func.count(BalanceEntry.id))) == 2


def test_topup_rolls_back_status_balance_and_bonus(database, monkeypatch):
    _, ids = database
    rid = request_id(ids)
    original = billing.credit
    def broken(s, c, amount, user_id, note):
        if 'бонус' in note: raise RuntimeError('simulated failure')
        return original(s, c, amount, user_id, note)
    monkeypatch.setattr(billing, 'credit', broken)
    with pytest.raises(RuntimeError): topups.resolve(master(ids), rid, 'paid')
    with db.session() as s:
        assert s.get(TopupRequest, rid).status == 'new'
        assert s.get(Client, ids['client']).balance_rub == 200
        assert s.scalar(select(func.count(BalanceEntry.id))) == 0


def test_charge_exact_rounding_and_master_bypass(database):
    _, ids = database
    with db.session() as s:
        assert billing.charge(s, ids['project'], [{'cost':'1.005', 'kind':'generation'}]) == 1.01
    billing.by_master.set(True)
    with db.session() as s:
        assert billing.charge(s, ids['project'], [{'cost':50}]) == 0
        assert s.get(Client, ids['client']).balance_rub == 198.99


def test_queue_duplicate_and_pending_guards(database):
    _, ids = database
    with db.session() as s:
        assert queue.enqueue(s, 'generate', ids['project'], product_id=ids['product'], frame_id=ids['frame'])
        assert queue.enqueue(s, 'check', ids['project'], frame_id=ids['frame']) is None
    with db.session() as s:
        s.scalar(select(Job)).status = 'done'
        s.add(Generation(frame_id=ids['frame'], status='pending', external_id='paid-task'))
    with db.session() as s:
        assert queue.enqueue(s, 'generate', ids['project'], frame_id=ids['frame']) is None


def test_database_rejects_duplicate_active_job(database):
    _, ids = database
    with db.session() as s:
        s.add(Job(project_id=ids['project'], frame_id=ids['frame'], kind='generate'))
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(Job(project_id=ids['project'], frame_id=ids['frame'], kind='check'))


@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_paid_submit_is_not_repeated_on_ambiguous_error(status, monkeypatch):
    response = SimpleNamespace(status_code=status, text='upstream failed', json=lambda:{}, headers={})
    post = Mock(return_value=response)
    monkeypatch.setattr(polza.http, 'post', post)
    monkeypatch.setattr(polza.throttle, 'limiter', lambda *a: Mock())
    with pytest.raises(RuntimeError): polza._submit({'Authorization':'Bearer fake'}, {}, 'test')
    assert post.call_count == 1


def test_paid_chat_read_timeout_is_not_repeated(monkeypatch):
    post = Mock(side_effect=requests.ReadTimeout('possibly paid'))
    monkeypatch.setattr(polza.http, 'post', post)
    monkeypatch.setattr(polza, 'qc_endpoint', lambda st:('https://fake', 'fake'))
    monkeypatch.setattr(polza.throttle, 'limiter', lambda *a: Mock())
    with pytest.raises(RuntimeError): polza.chat({}, 'fake', '', '', Trace('test'), 'qc')
    assert post.call_count == 1


@pytest.mark.parametrize('reply', [{}, {'defects':None}, {'defects':{}}, {'defects':[None]}, {'defects':[{}]}, {'defects':[], 'prohibited':False}])
def test_malformed_qc_never_passes(reply, monkeypatch):
    monkeypatch.setattr(qc, 'chat', lambda *a:(reply, 0, 0))
    with pytest.raises(ValueError): qc.vlm_check({'qc_model':'fake'}, '', [], 'data:image/png;base64,', Trace('test'))


def test_old_verification_link_cannot_open_another_session(database):
    _, ids = database
    with db.session() as s:
        u = User(org_id=ids['org'], email='verified@example.test', email_verified_at=utcnow())
        s.add(u); s.flush()
        s.add(EmailToken(id=hashlib.sha256(b'old-token').hexdigest(), user_id=u.id, kind='verify',
                         expires_at=utcnow()+timedelta(hours=1)))
    with pytest.raises(ValueError, match='уже подтверждена'):
        registration.verify('old-token', '', '')


def png():
    out = io.BytesIO(); Image.new('RGB', (64,64), 'white').save(out, 'PNG'); return out.getvalue()


def test_moderated_asset_permission_is_revoked_immediately(database, monkeypatch, tmp_path):
    _, ids = database
    monkeypatch.setattr(storage.config, 'STORAGE_DIR', tmp_path)
    with db.session() as s:
        asset = storage.put(s, ids['org'], png(), 'output', 'test.png')
        g = Generation(frame_id=ids['frame'], status='ok', output_asset_id=asset.id)
        s.add(g); s.flush(); aid, gid = asset.id, g.id
    user = SimpleNamespace(master=False, client_id=ids['client'], org_id=ids['org'])
    assert access.asset_allowed(user, aid)
    with db.session() as s: s.get(Generation, gid).status = 'blocked'
    assert not access.asset_allowed(user, aid)


@pytest.mark.postgres
def test_concurrent_enqueue(database):
    engine, ids = database
    if engine.dialect.name != 'postgresql': pytest.skip('PostgreSQL required')
    def put(_):
        with db.session() as s:
            return bool(queue.enqueue(s, 'generate', ids['project'], frame_id=ids['frame']))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(put, range(4))) == 1


@pytest.mark.postgres
def test_parallel_limit_across_projects_and_process_claims(database, monkeypatch):
    engine, ids = database
    if engine.dialect.name != 'postgresql': pytest.skip('PostgreSQL required')
    from dreamgoods.services import plans
    monkeypatch.setattr(plans, 'parallel_for', lambda s, cid: 1)
    with db.session() as s:
        p2 = Project(client_id=ids['client'], name='second'); s.add(p2); s.flush()
        s.add_all([Job(project_id=ids['project'], kind='test'), Job(project_id=p2.id, kind='test')])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i:queue._claim(str(i)), range(2)))
    assert sum(r is not None for r in results) == 1


@pytest.mark.postgres
def test_concurrent_topup(database):
    engine, ids = database
    if engine.dialect.name != 'postgresql': pytest.skip('PostgreSQL required')
    rid = request_id(ids)
    def pay(_):
        try: topups.resolve(master(ids), rid, 'paid'); return True
        except ValueError: return False
    with ThreadPoolExecutor(max_workers=2) as pool: assert sum(pool.map(pay, range(2))) == 1
    with db.session() as s: assert s.get(Client, ids['client']).balance_rub == 310


@pytest.mark.postgres
def test_concurrent_resume_charges_once(database, monkeypatch, tmp_path):
    engine, ids = database
    if engine.dialect.name != 'postgresql': pytest.skip('PostgreSQL required')
    monkeypatch.setattr(storage.config, 'STORAGE_DIR', tmp_path)
    with db.session() as s:
        j = Job(project_id=ids['project'], frame_id=ids['frame'], kind='generate', status='done')
        s.add(j); s.flush()
        g = Generation(frame_id=ids['frame'], job_id=j.id, model='test', status='pending', external_id='task')
        s.add(g); s.flush(); gid, created = g.id, g.created_at
        s.get(Project, ids['project']).settings = {'qc_enabled':False}
    monkeypatch.setattr(polza, 'get_task', lambda *a, **k:{'id':'task','status':'completed','usage':{'cost_rub':10}})
    monkeypatch.setattr(polza, 'extract_image', lambda data:png())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:resume._resume(gid, created), range(2))) == [0,1]
    with db.session() as s:
        assert s.scalar(select(func.count(BalanceEntry.id))) == 1
        assert s.scalar(select(func.count(UsageEntry.id))) == 1
        assert s.get(Client, ids['client']).balance_rub == 190


def test_qc_failure_records_cost_and_clears_old_pass(database, monkeypatch):
    _, ids = database
    from dreamgoods.workers import check
    with db.session() as s:
        g = Generation(frame_id=ids['frame'], status='ok')
        s.add(g); s.flush()
        f = s.get(Frame,ids['frame']); f.current_generation_id, f.status = g.id, 'pass'
        j = Job(project_id=ids['project'], frame_id=f.id, kind='check')
        s.add(j); s.flush(); jid=j.id
    monkeypatch.setattr(check, 'qc_refs', lambda *a:[])
    monkeypatch.setattr(check.storage, 'get', lambda *a:png())
    def broken(st, task, refs, img, trace):
        trace.add('qc', 'fake', 1)
        raise ValueError('malformed response')
    monkeypatch.setattr(check.qc, 'run_qc', broken)
    with pytest.raises(ValueError): check.handle(jid)
    with db.session() as s:
        assert s.get(Frame,ids['frame']).status == 'unchecked'
        assert s.get(Client,ids['client']).balance_rub == 199
        assert s.scalar(select(func.count(UsageEntry.id))) == 1


def test_cyrillic_download_header_and_cross_project_access(database, monkeypatch):
    _, ids = database
    from fastapi.testclient import TestClient
    from dreamgoods.api.app import create_app
    from urllib.parse import unquote
    with db.session() as s:
        asset = Asset(org_id=ids['org'],kind='output',storage_key='fake',sha256='fake',mime='image/png',bytes=1)
        s.add(asset); s.flush(); aid=asset.id
    user = auth.CurrentUser(1,ids['org'],'test','test','user',ids['client'])
    monkeypatch.setattr(auth,'user_by_token',lambda token:user)
    monkeypatch.setattr(access,'asset_allowed',lambda *a:True)
    monkeypatch.setattr(storage,'get',lambda *a:b'x')
    with TestClient(create_app(),cookies={auth.COOKIE:'test'}) as client:
        response = client.get(f'/api/assets/{aid}',params={'dl':'Ботинки'})
        assert response.status_code == 200
        assert 'Ботинки.png' in unquote(response.headers['content-disposition'])
        with db.session() as s:
            other = Client(org_id=ids['org'],name='Other'); s.add(other); s.flush()
            project = Project(client_id=other.id,name='Other'); s.add(project); s.flush(); other_id=project.id
        assert client.get(f'/api/projects/{other_id}/state').status_code == 403


def test_unexpected_api_error_does_not_expose_secrets(monkeypatch):
    from fastapi.testclient import TestClient
    from dreamgoods.api.app import create_app
    monkeypatch.setattr(auth,'user_by_token',lambda token:SimpleNamespace(master=True))
    app = create_app()
    @app.get('/api/test-error')
    def broken(): raise RuntimeError('password=private-value')
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app,raise_server_exceptions=False,cookies={auth.COOKIE:'fake'}) as client:
        response=client.get('/api/test-error')
        assert response.status_code == 500
        assert 'private-value' not in response.text


@pytest.mark.postgres
def test_saturated_client_does_not_starve_later_jobs(database,monkeypatch):
    engine,ids=database
    if engine.dialect.name != 'postgresql': pytest.skip('PostgreSQL required')
    from dreamgoods.services import plans
    monkeypatch.setattr(plans,'parallel_for',lambda s,cid:1)
    with db.session() as s:
        s.add(Job(project_id=ids['project'],kind='test',status='running'))
        s.add_all([Job(project_id=ids['project'],kind='test') for _ in range(35)])
        c=Client(org_id=ids['org'],name='Available');s.add(c);s.flush()
        p=Project(client_id=c.id,name='Available');s.add(p);s.flush()
        j=Job(project_id=p.id,kind='test');s.add(j);s.flush();jid=j.id
    assert queue._claim('test')[0] == jid


def test_failed_handler_keeps_known_paid_usage(database,monkeypatch):
    _,ids=database
    with db.session() as s:
        j=Job(project_id=ids['project'],product_id=ids['product'],kind='fake')
        s.add(j);s.flush();jid=j.id
    def broken(job_id):
        trace=Trace('failed profile')
        trace.add('profile','fake',2)
        raise ValueError('bad JSON after paid response')
    monkeypatch.setitem(queue.HANDLERS,'fake',broken)
    with pytest.raises(ValueError):queue._run_handler(jid,'fake')
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub == 198
        assert s.scalar(select(func.count(UsageEntry.id))) == 1


def test_handler_does_not_charge_flushed_usage_twice(database,monkeypatch):
    _,ids=database
    from dreamgoods.services.common import write_usage
    with db.session() as s:
        j=Job(project_id=ids['project'],kind='fake');s.add(j);s.flush();jid=j.id
    def successful(job_id):
        trace=Trace('success');trace.add('profile','fake',3)
        with db.session() as s:
            write_usage(s,ids['org'],ids['project'],None,None,trace,'profile:test')
    monkeypatch.setitem(queue.HANDLERS,'fake',successful)
    queue._run_handler(jid,'fake')
    with db.session() as s:
        assert s.get(Client,ids['client']).balance_rub == 197
        assert s.scalar(select(func.count(UsageEntry.id))) == 1


@pytest.mark.parametrize('configured', ['', 'admin'])
def test_local_bootstrap_keeps_default_login(database,monkeypatch,configured):
    _,ids=database
    monkeypatch.setattr(auth.config,'app_env',lambda name,default='':configured if name=='ADMIN_PASSWORD' else default)
    auth.bootstrap_master(ids['org'])
    with db.session() as s:
        u=s.scalar(select(User).where(User.role=='master'))
        assert u.email=='admin' and auth.check_password('admin',u.password_hash)
    token,user=auth.login('admin','admin')
    assert token and user.master


def test_zero_markup_is_preserved(database):
    _,ids=database
    with db.session() as s:
        s.get(Organization,ids['org']).settings={'markup':0}
    with db.session() as s:
        assert billing.charge(s,ids['project'],[{'cost':10}])==0
        assert s.get(Client,ids['client']).balance_rub==200


@pytest.mark.parametrize('entity',[{'name':'shoe','expected':'2'},{'name':'shoe','expected':-1},{}])
def test_invalid_expected_object_is_not_silently_dropped(database,monkeypatch,entity):
    monkeypatch.setattr(qc,'chat',lambda *a:({'people':0,'entities':[entity],'forbidden':[]},0,0))
    with pytest.raises(ValueError):qc.task_spec({'qc_model':'fake'},'two shoes',Trace('test'))


def test_bootstrap_repairs_only_provisioned_master_without_changing_password(database,monkeypatch):
    _,ids=database
    monkeypatch.setattr(auth.config,'app_env',lambda name,default='':default)
    original=auth.hash_password('saved-local-password')
    with db.session() as s:
        s.add(User(org_id=ids['org'],email='admin',role='master',password_hash=original))
        s.add(User(org_id=ids['org'],email='unverified@example.test',role='user',password_hash=auth.hash_password('unchanged')))
    auth.bootstrap_master(ids['org'])
    with db.session() as s:
        assert s.scalar(select(User).where(User.email=='admin')).password_hash==original
        assert s.scalar(select(User).where(User.email=='unverified@example.test')).email_verified_at is None
    assert auth.login('admin','saved-local-password')[1].master
    with pytest.raises(auth.Forbidden,match='почта не подтверждена'): auth.login('unverified@example.test','unchanged')
