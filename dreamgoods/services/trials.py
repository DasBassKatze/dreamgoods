"""Один пробный кадр и явное утверждение перед постановкой подготовленной партии."""
import hashlib
import json
from sqlalchemy import select
from .. import db
from ..db.models import Product, ProductPhoto, Frame, Generation, Job, Project, Review, QCCheck, ProductProfile
from ..workers.queue import ACTIVE, enqueue
from .common import context
from . import preflight


def _products(s,pid,ids):
    q=select(Product).where(Product.project_id==pid).order_by(Product.sku,Product.id)
    if ids is not None:q=q.where(Product.id.in_(ids))
    return s.scalars(q).all()


def _signature(s,products):
    values=[]
    for p in products:
        st={k:v for k,v in context(s,p)[2].items() if not any(x in k.lower() for x in ('key','token','secret'))}
        photos=s.scalars(select(ProductPhoto).where(ProductPhoto.product_id==p.id).order_by(ProductPhoto.id)).all()
        frames=s.scalars(select(Frame).where(Frame.product_id==p.id,Frame.status!='retired').order_by(Frame.position)).all()
        from ..workers.refs import persona_for, style_for
        persona,persona_assets=persona_for(s,p,st)
        style,style_assets=style_for(s,p,st)
        profile=s.get(ProductProfile,p.current_profile_id) if p.current_profile_id else None
        appearance=[
            [persona.id,persona.description,persona.style,[str(a.id) for a in persona_assets]] if persona else None,
            [style.id,style.description,style.note,[str(a.id) for a in style_assets]] if style else None,
        ]
        values.append([p.id,p.current_profile_id,profile.data if profile else None,p.label_data,st,appearance,
                       [[str(x.asset_id),x.is_reference,x.role] for x in photos],
                       [[f.id,f.prompt,f.model,f.block] for f in frames]])
    return hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()


def start(pid,ids=None):
    report=preflight.inspect_sources(pid,ids)
    if not report['products']:raise ValueError('Нет товаров для пробной съёмки')
    if report['errors']:raise ValueError('Исправьте ошибки исходников перед пробной съёмкой')
    if any(i['code'] in ('no_profile','no_frames') for p in report['products'] for i in p['issues']):
        raise ValueError('Сначала подготовьте профили и план кадров выбранных товаров')
    with db.session() as s:
        s.get(Project,pid,with_for_update=True)
        products=_products(s,pid,ids)
        pids=[p.id for p in products]
        if s.scalar(select(Job.id).where(Job.project_id==pid,Job.product_id.in_(pids),Job.status.in_(ACTIVE)).limit(1)):
            raise ValueError('Дождитесь завершения заданий выбранных товаров')
        frame=s.scalar(select(Frame).where(Frame.product_id==pids[0],Frame.status!='retired').order_by(Frame.position))
        j=enqueue(s,'generate',pid,product_id=frame.product_id,frame_id=frame.id,priority=50,
                  payload={'trial_only':True,'trial_product_ids':pids,'trial_signature':_signature(s,products)})
        if not j:raise ValueError('Пробный кадр уже в работе или ожидает оплаченный результат')
        return _view(s,j)


def _view(s,j):
    f=s.get(Frame,j.frame_id)
    g=s.get(Generation,f.current_generation_id) if f and f.current_generation_id else None
    valid=g is not None and g.job_id==j.id and g.status=='ok' and g.output_asset_id is not None
    return dict(id=j.id,frame_id=j.frame_id,product_id=j.product_id,status="done" if valid and j.status not in ACTIVE else j.status,error="" if valid else j.error,
                asset=str(g.output_asset_id) if valid else None,generation=g.id if valid else None,
                approved=bool((j.payload or {}).get('trial_approved')),products=len((j.payload or {}).get('trial_product_ids',[])))


def latest(pid):
    with db.session() as s:
        j=s.scalar(select(Job).where(Job.project_id==pid,Job.payload['trial_only'].as_boolean().is_(True)).order_by(Job.id.desc()).limit(1))
        return _view(s,j) if j else None


def approve(pid,job_id,generation_id):
    with db.session() as s:
        s.get(Project,pid,with_for_update=True)
        j=s.get(Job,job_id)
        if not j or j.project_id!=pid or not (j.payload or {}).get('trial_only'):raise LookupError('Пробная съёмка не найдена')
        payload=dict(j.payload)
        if payload.get('trial_approved'):return {'added':0,'already_approved':True}
        f=s.get(Frame,j.frame_id,with_for_update=True)
        g=s.get(Generation,generation_id)
        if j.status in ACTIVE or not f or f.current_generation_id!=generation_id or not g or g.job_id!=j.id or g.status!='ok' or not g.output_asset_id:
            raise ValueError('Пробный кадр ещё не готов или версия изменилась')
        products=_products(s,pid,payload['trial_product_ids'])
        if len(products)!=len(payload['trial_product_ids']) or _signature(s,products)!=payload['trial_signature']:
            raise ValueError('Исходники, план или настройки изменились. Сделайте новый пробный кадр.')
        # Партия и отметка утверждения записываются одной транзакцией.
        added=0
        fs=s.scalars(select(Frame).where(Frame.product_id.in_([p.id for p in products]),Frame.status!='retired',
                                         Frame.current_generation_id.is_(None)).order_by(Frame.product_id,Frame.position)).all()
        for frame in fs:
            if enqueue(s,'generate',pid,product_id=frame.product_id,frame_id=frame.id):added+=1
        q=s.scalar(select(QCCheck).where(QCCheck.generation_id==generation_id).order_by(QCCheck.id.desc()).limit(1))
        s.add(Review(frame_id=f.id,generation_id=g.id,verdict='ok',ai_verdict=('pass' if q.passed else 'fail') if q else '',
                     comment='Утверждён пробный кадр перед партией',note_kind='note'))
        f.status='accepted'
        payload['trial_approved']=generation_id
        j.payload=payload
        return {'added':added,'already_approved':False}


def product_ids(pid,job_id):
    with db.session() as s:
        j=s.get(Job,job_id)
        if not j or j.project_id!=pid or not (j.payload or {}).get('trial_only'):
            raise LookupError('Пробная съёмка не найдена')
        return j.payload['trial_product_ids']
