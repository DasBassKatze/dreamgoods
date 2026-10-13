"""Доступ к файлам: пользователь видит только картинки своего клиента (фото товаров, кадры, модели, оформление,
файлы импорта). Мастер — все. Результат проверки кэшируется — превью грузятся десятками."""
import threading
import time

from sqlalchemy import select

from .. import db
from ..db.models import (Frame, Generation, ImportFile, ImportSession, Persona, PersonaPhoto, Product, ProductPhoto, Project,
                         StyleRef, StyleRefPhoto)

_cache, _lock = {}, threading.Lock()        # (client_id, asset_id) → (разрешено, до какого времени)


def _clients_of(s, aid):
    q = [
        select(Project.client_id).join(Product, Product.project_id == Project.id)
        .join(ProductPhoto, ProductPhoto.product_id == Product.id).where(ProductPhoto.asset_id == aid),
        select(Project.client_id).join(Product, Product.project_id == Project.id).join(Frame, Frame.product_id == Product.id)
        .join(Generation, Generation.frame_id == Frame.id).where(Generation.output_asset_id == aid),
        select(Persona.client_id).join(PersonaPhoto, PersonaPhoto.persona_id == Persona.id).where(PersonaPhoto.asset_id == aid),
        select(StyleRef.client_id).join(StyleRefPhoto, StyleRefPhoto.style_ref_id == StyleRef.id)
        .where(StyleRefPhoto.asset_id == aid),
        select(Project.client_id).join(ImportSession, ImportSession.project_id == Project.id)
        .join(ImportFile, ImportFile.session_id == ImportSession.id).where(ImportFile.asset_id == aid),
    ]
    out = set()
    for x in q:
        out.update(s.scalars(x.limit(5)).all())
    return out


def asset_allowed(user, asset_id):
    if user.master:
        return True
    key = (user.client_id, asset_id)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and hit[1] > now:
        return hit[0]
    with db.session() as s:
        ok = (user.client_id or -1) in _clients_of(s, asset_id)
    with _lock:
        if len(_cache) > 50000:
            _cache.clear()
        _cache[key] = (ok, now + (600 if ok else 15))
    return ok
