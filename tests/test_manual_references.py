import io
import pytest
from PIL import Image
from sqlalchemy import select
from dreamgoods import db
from dreamgoods.ai import prompts
from dreamgoods.core import presets as P, storage
from dreamgoods.db.models import Frame, StyleRef, StyleRefPhoto, Product, Project, Client, GenerationPreset
from dreamgoods.services import presets, styles
from dreamgoods.services.common import rebuild_frames
from dreamgoods.workers.refs import style_for


def test_reference_roundtrip_in_manual_prompt():
    items = P.clean_manual([dict(title='Метод',prompt='on marble',block='studio',count=1,reference_id=7,
                                 reference_description='soft side light')])
    assert items[0]['reference_id'] == 7
    assert 'soft side light' in prompts.build_manual({'noun':'shoe'},items)[0][0]


def test_references_are_client_scoped_and_not_shared(database):
    _, ids = database
    with db.session() as s:
        client=Client(org_id=ids['org'],name='Other');s.add(client);s.flush()
        ref=StyleRef(client_id=client.id,name='Private',status='ready');s.add(ref);s.flush();rid=ref.id
    data=dict(name='Manual',plan_mode='manual',manual=[dict(prompt='on marble',count=1,block='studio',reference_id=rid)],market={'key':'none'})
    with pytest.raises(LookupError): presets.save(ids['project'],None,data,master=True)
    with db.session() as s:
        ref=StyleRef(client_id=ids['client'],name='Own',status='draft');s.add(ref);s.flush();rid=ref.id
    data['manual'][0]['reference_id']=rid
    data['shared']=True
    with pytest.raises(ValueError,match='собственном'): presets.save(ids['project'],None,data,master=True)
    data['shared']=False
    pid=presets.save(ids['project'],None,data,master=True)
    with db.session() as s:
        assert s.get(GenerationPreset,pid).manual[0]['reference_id']==rid


def test_frame_rebuild_tracks_reference_and_rejects_archived(database,monkeypatch):
    _,ids=database
    from dreamgoods.services import common
    with db.session() as s:
        ref=StyleRef(client_id=ids['client'],name='Shot',status='draft');s.add(ref);s.flush();rid=ref.id
        s.add(StyleRefPhoto(style_ref_id=rid,asset=storage.put(s,ids['org'],b'photo','style','x.png'),position=1))
    manual=P.clean_manual([dict(prompt='on marble',title='Shot',count=1,block='studio',reference_id=rid)])
    monkeypatch.setattr(common,'context',lambda s,p:(None,None,{'plan_mode':'manual','manual':manual}))
    with db.session() as s:
        product=s.get(Product,ids['product'])
        rebuild_frames(s,product,{'noun':'shoe'})
        frame=s.get(Frame,ids['frame']);assert frame.shot_reference_id==rid
        ref,assets=style_for(s,product,{},frame.shot_reference_id);assert ref.id==rid and len(assets)==1
        ref.status='archived';s.flush()
        with pytest.raises(ValueError,match='недоступен'): style_for(s,product,{},rid)
        manual[0]['reference_id']=0
        rebuild_frames(s,product,{'noun':'shoe'})
        assert frame.shot_reference_id is None


def test_upload_rejects_bad_or_oversized_reference(database):
    _,ids=database
    rid=styles.create(ids['project'],'Ref','',[])
    with pytest.raises(ValueError,match='прочитать'): styles.upload_photo(ids['project'],rid,b'not an image','x.png')
    with pytest.raises(ValueError,match='20'): styles.upload_photo(ids['project'],rid,b'X'*(20*1024*1024+1),'x.png')


def test_reference_only_method_and_cover_rules():
    item=P.clean_manual([dict(reference_id=7,reference_description='neon purple wall',block='studio',count=2)])[0]
    assert item['prompt']
    rows=prompts.build_manual({'noun':'shoe'},[item],{'cover':True,'name':'WB'})
    assert 'neon purple wall' not in rows[0][0]
    assert 'neon purple wall' in rows[1][0]
