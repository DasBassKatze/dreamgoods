"""Референсы товара для генерации и для проверки (с ракурсами)."""
import threading
from collections import OrderedDict

from sqlalchemy import select

from .. import db
from ..ai.images import jpeg_data_url
from ..ai import views
from ..core import storage
from ..core.logs import log
from ..db.models import Persona, PersonaPhoto, ProductPhoto, StyleRef, StyleRefPhoto
from ..services.common import persona_id_for, write_usage


def ref_photos(s, product, limit):
    """Отмеченные референсы товара в порядке показа (этикетки не берутся)."""
    return s.scalars(select(ProductPhoto).where(ProductPhoto.product_id == product.id, ProductPhoto.is_reference.is_(True),
                                                ProductPhoto.role != "label")
                     .order_by(ProductPhoto.position, ProductPhoto.id).limit(limit)).all()


def persona_for(s, product, st):
    """Модель клиента для кадров товара: своя у товара → по группе товаров → модель проекта.
    Возвращает (Persona, [Asset]) или (None, [])."""
    pid, _ = persona_id_for(s, product, st)
    p = s.get(Persona, pid) if pid else None
    if not p or p.status != "ready":
        return None, []
    order = {"main": 0, "photo": 1, "sheet": 2}
    photos = sorted(s.scalars(select(PersonaPhoto).where(PersonaPhoto.persona_id == p.id,
                                                        PersonaPhoto.kind.in_(tuple(order)))).all(),
                    key=lambda x: (order[x.kind], x.position, x.id))
    return p, [x.asset for x in photos[:max(1, int(st.get("persona_refs") or 2))]]


def style_for(s, product, st, shot_reference_id=None):
    """Референс оформления товара: свой или проекта. Возвращает (StyleRef, [Asset]) или (None, [])."""
    sid = shot_reference_id or product.style_ref_id or int(st.get("style_ref_id") or 0)
    r = s.get(StyleRef, sid) if sid else None
    if shot_reference_id:
        from ..db.models import Project
        project = s.get(Project, product.project_id)
        if not r or r.client_id != project.client_id or r.status == "archived":
            raise ValueError("референс метода недоступен — замените его в ручном плане")
    if not r or (r.status != "ready" and not shot_reference_id):
        return None, []
    photos = s.scalars(select(StyleRefPhoto).where(StyleRefPhoto.style_ref_id == r.id)
                       .order_by(StyleRefPhoto.position, StyleRefPhoto.id).limit(2)).all()
    if shot_reference_id and not photos:
        raise ValueError("в референсе метода нет фото — загрузите его заново")
    return r, [x.asset for x in photos]


_locks, _guard = {}, threading.Lock()


def qc_refs(product_id, st, ids, trace):
    """Все референсы товара с ракурсами для проверки. Неподписанные фото ИИ подписывает один раз (сохраняется в базе).
    Блокировка на товар: параллельные задания одного товара не платят за подпись повторно."""
    with _guard:
        lock = _locks.setdefault(product_id, threading.Lock())
    with lock:
        return _qc_refs(product_id, st, ids, trace)


_qc_cache, _qc_lock = OrderedDict(), threading.Lock()


def _qc_url(asset):
    """Фото товара для проверки — JPEG 768 px (кэш: в памяти не держим оригиналы по 5–10 МБ на каждое задание)."""
    k = asset.storage_key
    with _qc_lock:
        if k in _qc_cache:
            _qc_cache.move_to_end(k)
            return _qc_cache[k]
    url = jpeg_data_url(storage.get(asset), 768)
    with _qc_lock:
        _qc_cache[k] = url
        while len(_qc_cache) > 600:
            _qc_cache.popitem(last=False)
    return url


def _qc_refs(product_id, st, ids, trace):
    with db.session() as s:
        photos = s.scalars(select(ProductPhoto).where(ProductPhoto.product_id == product_id, ProductPhoto.is_reference.is_(True),
                                                      ProductPhoto.role != "label")
                           .order_by(ProductPhoto.position, ProductPhoto.id).limit(12)).all()
        items = [(p.id, p.asset, p.view, p.view_note) for p in photos]
    unknown = [(pid, a) for pid, a, v, _ in items if not v]
    labels = {}
    if unknown:     # ракурсы ещё не подписаны — один раз, оригиналы нужны только здесь
        try:
            res = views.classify_views(st, [storage.get(a) for _, a in unknown], trace)
            labels = dict(zip([pid for pid, _ in unknown], res))
            with db.session() as s:
                for pid, (v, note) in labels.items():
                    ph = s.get(ProductPhoto, pid)
                    ph.view, ph.view_note = v, note
                write_usage(s, ids["org"], ids["project"], ids["product"], None, trace, "views")
        except Exception as e:
            log.warning("%s ракурсы референсов не определены (%s) — проверка без них", trace, e)
            trace.usage.clear()
    out = []
    for pid, a, v, note in items:
        v2, n2 = labels.get(pid, (v, note))
        out.append({"url": _qc_url(a), "view": v2 or "", "note": n2 or ""})
    return out

