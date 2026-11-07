import io
from types import SimpleNamespace
import pytest
from PIL import Image
from sqlalchemy import select, func, text
from dreamgoods import db
from dreamgoods.core import auth, storage
from dreamgoods.db.models import Product, ProductPhoto, Frame, Generation, Job, ImportFile, ImportSession, UsageEntry
from dreamgoods.services import importer, products
from dreamgoods.api.routers import settings


def upload_setup(ids, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.config, 'STORAGE_DIR', tmp_path)
    monkeypatch.setattr(storage.config, 'STORAGE', 'local')
    image=io.BytesIO();Image.new('RGB',(20,20),'blue').save(image,format='PNG')
    sid=importer.new_session(ids['project'])
    importer.save_upload(sid,'one.png',image.getvalue())
    importer.save_upload(sid,'two.png',image.getvalue())
    return sid


def test_same_article_preview_and_distinct_real_suffix():
    result=importer.merge_article_groups([
        {'id':'a','name':'ART','article':'ART','articles':['ART'],'photos':['one']},
        {'id':'b','name':'ART_2','article':'art','articles':['art'],'photos':['two']},
        {'id':'c','name':'ART_2','article':'ART_2','articles':['ART_2'],'photos':['three']},
    ])
    assert len(result)==2 and result[0]['photos']==['one','two']
    assert result[1]['name']=='ART_2'


def test_same_article_apply_and_repeated_upload_merge(database, monkeypatch, tmp_path):
    _,ids=database;sid=upload_setup(ids,monkeypatch,tmp_path)
    with db.session() as s:
        for f in s.scalars(select(ImportFile).where(ImportFile.session_id==sid)):
            f.analysis={'article':'ＡＲＴ 123'}
    groups=[{'name':'ART123','photos':[['one.png','product']]},{'name':'ART123_2','photos':[['two.png','product']]}]
    result=importer.apply(sid,groups,'read',False)
    assert len(result['folders'])==1
    with db.session() as s:
        matching=[p for p in s.scalars(select(Product)) if importer._art(p.sku)=='ART123']
        assert len(matching)==1
        pid=matching[0].id
        assert s.scalar(select(func.count(ProductPhoto.id)).where(ProductPhoto.product_id==pid))==2
    sid2=upload_setup(ids,monkeypatch,tmp_path)
    importer.apply(sid2,[{'name':'art123','article':'art123','photos':[['one.png','product']]}],'read',False)
    with db.session() as s:
        assert len([p for p in s.scalars(select(Product)) if importer._art(p.sku)=='ART123'])==1
        assert not s.scalar(select(Product.id).where(Product.sku=='ART123_2'))


def test_import_remove_selected_files_and_busy_guard(database, monkeypatch, tmp_path):
    _,ids=database;sid=upload_setup(ids,monkeypatch,tmp_path)
    assert len(importer.view(sid)['photos'])==2
    with db.session() as s:
        session=s.get(ImportSession,sid);session.status='analyzing'
        s.add(Job(project_id=ids['project'],kind='import',status='running',payload={'session':sid}))
    with pytest.raises(ValueError): importer.remove_files(sid,['one.png'])
    with db.session() as s:
        s.get(ImportSession,sid).status='ready';s.get(ImportSession,sid).groups=[{'photos':['one.png','two.png']}]
    view=importer.remove_files(sid,['one.png'])
    assert view['count']==1 and view['photos'][0]['name']=='two.png'
    assert view['groups'][0]['photos']==['two.png']
    with pytest.raises(LookupError): importer.remove_files(sid,['other.png'])


def test_product_deletion_explicit_scope_busy_and_financial_history(database):
    engine,ids=database
    if engine.dialect.name=='sqlite':
        with engine.connect() as c: c.execute(text('PRAGMA foreign_keys=ON'))
    with pytest.raises(ValueError): products.delete_products(ids['project'],[])
    with pytest.raises(LookupError): products.delete_products(ids['project'],[ids['product']+999])
    with db.session() as s:
        job=Job(project_id=ids['project'],product_id=ids['product'],kind='profile',status='running');s.add(job);s.flush();jid=job.id
    with pytest.raises(ValueError,match='активные'): products.delete_products(ids['project'],[ids['product']])
    with db.session() as s:
        s.get(Job,jid).status='done'
        s.add(UsageEntry(org_id=ids['org'],project_id=ids['project'],product_id=ids['product'],kind='generation',model='test',amount_rub=2))
    assert products.delete_products(ids['project'],[ids['product']])['deleted']==1
    with db.session() as s:
        assert s.get(Product,ids['product']) is None
        assert s.scalar(select(func.count(Frame.id)))==0
        assert s.scalar(select(UsageEntry)).product_id is None


def test_key_status_uses_effective_key_and_never_returns_secret(database,monkeypatch):
    _,ids=database
    request=SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(master=True)))
    monkeypatch.setattr(settings.projects,'project_settings',lambda pid:{'api_key':'secret-key'})
    monkeypatch.setattr(settings.polza,'balance',lambda key:{'value':100,'error':'','busy':False,'t':123})
    result=settings.key_status(request,ids['project'])
    assert result['value']==100 and result['checked_at']==123 and 'secret-key' not in str(result)
    request.state.user.master=False
    with pytest.raises(auth.Forbidden): settings.key_status(request,ids['project'])
