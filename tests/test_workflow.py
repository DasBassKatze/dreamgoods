from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from sqlalchemy import func,select
from dreamgoods import db
from dreamgoods.db.models import Asset,ProductPhoto,ProductProfile,Product,Frame,Generation,Job,Project,Review
from dreamgoods.services import preflight,trials,frames
from dreamgoods.api.routers import workflow

@pytest.fixture
def prepared(database):
    engine,ids=database
    with db.session() as s:
        a=Asset(org_id=ids['org'],kind='photo',storage_key='test',sha256='source',mime='image/png',bytes=100,width=1200,height=1600)
        s.add(a);s.flush()
        s.add(ProductPhoto(product_id=ids['product'],asset_id=a.id,view='front'))
        pp=ProductProfile(product_id=ids['product'],version=1,data={'category':'shoes'})
        s.add(pp);s.flush();s.get(Product,ids['product']).current_profile_id=pp.id
        s.add(Frame(product_id=ids['product'],position=2,prompt='Shot: sole view.'))
    return engine,ids


def complete(ids,trial):
    with db.session() as s:
        j=s.get(Job,trial['id']);j.status='done'
        a=Asset(org_id=ids['org'],kind='output',storage_key='output',sha256='result',mime='image/png',bytes=100)
        s.add(a);s.flush()
        g=Generation(frame_id=trial['frame_id'],job_id=j.id,status='ok',output_asset_id=a.id)
        s.add(g);s.flush();s.get(Frame,trial['frame_id']).current_generation_id=g.id
        return g.id


def test_preflight_does_not_call_ai_or_create_jobs(database):
    _,ids=database
    report=preflight.inspect_sources(ids['project'])
    assert report['errors']==1
    assert 'no_refs' in {i['code'] for i in report['products'][0]['issues']}
    with db.session() as s:assert s.scalar(select(func.count(Job.id)))==0


def test_preflight_reports_missing_known_angle_and_small_reference(prepared):
    _,ids=prepared
    with db.session() as s:s.scalar(select(Asset)).width=400
    report=preflight.inspect_sources(ids['project'])
    codes={i['code'] for i in report['products'][0]['issues']}
    assert 'missing_view' in codes and 'small' in codes
    assert report['errors']==0


def test_empty_selection_does_not_expand_to_entire_project(prepared):
    _,ids=prepared
    assert preflight.inspect_sources(ids['project'],[])['products']==[]
    with pytest.raises(ValueError):trials.start(ids['project'],[])


def test_trial_enqueues_exactly_one_image(prepared):
    _,ids=prepared
    trial=trials.start(ids['project'])
    with db.session() as s:
        jobs=s.scalars(select(Job)).all()
        assert len(jobs)==1 and jobs[0].payload['trial_only'] is True
    assert trial['frame_id']==ids['frame']
    with pytest.raises(ValueError):trials.start(ids['project'])


def test_trial_cannot_be_approved_before_result(prepared):
    _,ids=prepared
    trial=trials.start(ids['project'])
    with pytest.raises(ValueError):trials.approve(ids['project'],trial['id'],123)
    with db.session() as s:assert s.scalar(select(func.count(Job.id)))==1


def test_approval_enqueues_remainder_once(prepared):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    result=trials.approve(ids['project'],trial['id'],gid)
    assert result['added']==1
    assert trials.approve(ids['project'],trial['id'],gid)['already_approved']
    with db.session() as s:assert s.scalar(select(func.count(Job.id)))==2


@pytest.mark.parametrize('change',['source','prompt','settings','profile','profile_data'])
def test_changed_inputs_require_new_trial(prepared,change):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    with db.session() as s:
        if change=='source':s.scalar(select(ProductPhoto)).is_reference=False
        elif change=='prompt':s.get(Frame,ids['frame']).prompt='Changed'
        elif change=='settings':s.get(Project,ids['project']).settings={'aspect':'1:1'}
        elif change=='profile_data':s.scalar(select(ProductProfile)).data={'category':'other'}
        else:s.get(Product,ids['product']).label_data={'user_text':'other product'}
    with pytest.raises(ValueError,match='изменились'):trials.approve(ids['project'],trial['id'],gid)
    with db.session() as s:assert s.scalar(select(func.count(Job.id)))==1


def test_automatic_angle_detection_does_not_invalidate_trial(prepared):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    with db.session() as s:s.scalar(select(ProductPhoto)).view='side'
    assert trials.approve(ids['project'],trial['id'],gid)['added']==1


def test_recovered_trial_result_can_be_approved(prepared):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    with db.session() as s:s.get(Job,trial['id']).status='error'
    assert trials.latest(ids['project'])['status']=='done'
    assert trials.approve(ids['project'],trial['id'],gid)['added']==1


def test_stale_manual_review_is_rejected(prepared):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    with pytest.raises(ValueError,match='изменилась'):frames.review(ids['project'],ids['frame'],'ok','',False,expected_generation=gid+1)
    with db.session() as s:assert s.scalar(select(func.count(Review.id)))==0


def test_batch_review_reports_partial_results(prepared):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    body=workflow.BatchReview(items=[{'frame_id':ids['frame'],'generation_id':gid},{'frame_id':999999,'generation_id':gid}],verdict='ok')
    result=workflow.review(body,SimpleNamespace(),pid=ids['project'])
    assert [x['ok'] for x in result['results']]==[True,False]
    with db.session() as s:assert s.get(Frame,ids['frame']).status=='accepted'


def test_foreign_trial_cannot_be_approved(prepared):
    _,ids=prepared
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    with pytest.raises(LookupError):trials.approve(ids['project']+100,trial['id'],gid)


@pytest.mark.postgres
def test_concurrent_trial_approval_is_once(prepared):
    engine,ids=prepared
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL required')
    trial=trials.start(ids['project']);gid=complete(ids,trial)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:trials.approve(ids['project'],trial['id'],gid),range(2)))
    assert sum(r['added'] for r in results)==1
    with db.session() as s:assert s.scalar(select(func.count(Job.id)))==2
