"""Бесплатная проверка известных данных исходной съёмки, без обращения к ИИ."""
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from .. import db
from ..ai.views import shot_view, NEIGHBORS, VIEW_RU
from ..db.models import Product, ProductPhoto, ProductProfile, Frame


def inspect_sources(project_id, product_ids=None):
    with db.session() as s:
        q=select(Product).where(Product.project_id==project_id).order_by(Product.sku,Product.id)
        if product_ids is not None:
            q=q.where(Product.id.in_(product_ids))
        products=s.scalars(q).all()
        pids=[p.id for p in products]
        photos=s.scalars(select(ProductPhoto).options(joinedload(ProductPhoto.asset)).where(ProductPhoto.product_id.in_(pids))).all() if pids else []
        frames=s.scalars(select(Frame).where(Frame.product_id.in_(pids),Frame.status!='retired')).all() if pids else []
        by_photos={}; by_frames={}
        for photo in photos:by_photos.setdefault(photo.product_id,[]).append(photo)
        for frame in frames:by_frames.setdefault(frame.product_id,[]).append(frame)
        profile_ids=[p.current_profile_id for p in products if p.current_profile_id]
        profiles={x.id:x for x in s.scalars(select(ProductProfile).where(ProductProfile.id.in_(profile_ids))).all()} if profile_ids else {}
        out=[]
        for p in products:
            ps=by_photos.get(p.id,[])
            refs=[x for x in ps if x.is_reference and x.role=='product']
            issues=[]
            def add(code,level,text): issues.append(dict(code=code,level=level,text=text))
            if not refs: add('no_refs','error','Выберите хотя бы одно фото товара как референс.')
            if refs and len(refs)==1: add('one_ref','warning','Только один ракурс: скрытые детали модели придётся додумывать.')
            seen=set()
            for ph in refs:
                a=ph.asset
                if a.sha256 in seen: add('duplicate','warning','Среди выбранных референсов есть одинаковые изображения.');break
                seen.add(a.sha256)
            small=[ph for ph in refs if ph.asset.width and ph.asset.height and min(ph.asset.width,ph.asset.height)<768]
            if small: add('small','warning',f'Референсов с короткой стороной меньше 768 px: {len(small)}. Загрузите оригиналы крупнее.')
            if refs and any(not x.view for x in refs): add('unknown_view','info','Часть ракурсов ещё не определена. Полноту съёмки проверить нельзя.')
            known={x.view for x in refs if x.view}
            needed={shot_view(f.prompt) for f in by_frames.get(p.id,[])}
            if known and all(x.view for x in refs):
                for view in sorted(needed-{'','unknown'}):
                    if view in NEIGHBORS and not known.intersection(NEIGHBORS[view]):
                        add('missing_view','warning',f'Для кадра «{VIEW_RU.get(view,view)}» нет референса с этой или соседней стороны.')
            if not p.current_profile_id: add('no_profile','warning','Нет профиля товара: сначала составьте профиль и план кадров.')
            elif (profiles[p.current_profile_id].data or {}).get('prohibited'):
                add('blocked','error','Товар отмечен модерацией. Проверьте исходники и профиль.')
            if not by_frames.get(p.id): add('no_frames','warning','План кадров ещё не подготовлен.')
            out.append(dict(id=p.id,sku=p.sku,references=len(refs),issues=issues))
        return dict(products=out,errors=sum(any(i['level']=='error' for i in p['issues']) for p in out),
                    warnings=sum(any(i['level']=='warning' for i in p['issues']) for p in out),
                    note='Проверка использует размеры файлов и сохранённые метки. Содержимое фото и читаемость бирок автоматически не оцениваются.')
