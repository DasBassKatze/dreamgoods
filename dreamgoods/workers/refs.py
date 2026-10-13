"""Референсы товара для генерации и для проверки (с ракурсами)."""
import threading

from sqlalchemy import select

from .. import db
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


def style_for(s, product, st):
    """Референс оформления товара: свой или проекта. Возвращает (StyleRef, [Asset]) или (None, [])."""
    sid = product.style_ref_id or int(st.get("style_ref_id") or 0)
    r = s.get(StyleRef, sid) if sid else None
    if not r or r.status != "ready":
        return None, []
    photos = s.scalars(select(StyleRefPhoto).where(StyleRefPhoto.style_ref_id == r.id)
                       .order_by(StyleRefPhoto.position, StyleRefPhoto.id).limit(2)).all()
    return r, [x.asset for x in photos]


_locks, _guard = {}, threading.Lock()


def qc_refs(product_id, st, ids, trace):
    """Все референсы товара с ракурсами для проверки. Неподписанные фото ИИ подписывает один раз (сохраняется в базе).
    Блокировка на товар: параллельные задания одного товара не платят за подпись повторно."""
    with _guard:
        lock = _locks.setdefault(product_id, threading.Lock())
    with lock:
        return _qc_refs(product_id, st, ids, trace)


def _qc_refs(product_id, st, ids, trace):
    with db.session() as s:
        photos = s.scalars(select(ProductPhoto).where(ProductPhoto.product_id == product_id, ProductPhoto.is_reference.is_(True),
                                                      ProductPhoto.role != "label")
                           .order_by(ProductPhoto.position, ProductPhoto.id).limit(12)).all()
        items = [(p.id, p.asset, p.view, p.view_note) for p in photos]
    data = {pid: storage.get(a) for pid, a, _, _ in items}
    unknown = [pid for pid, _, v, _ in items if not v]
    labels = {}
    if unknown:
        try:
            res = views.classify_views(st, [data[pid] for pid in unknown], trace)
            labels = dict(zip(unknown, res))
            with db.session() as s:
                for pid, (v, note) in labels.items():
                    ph = s.get(ProductPhoto, pid)
                    ph.view, ph.view_note = v, note
                write_usage(s, ids["org"], ids["project"], ids["product"], None, trace, "views")
        except Exception as e:
            log.warning("%s ракурсы референсов не определены (%s) — проверка без них", trace, e)
            trace.usage.clear()
    out = []
    for pid, _, v, note in items:
        v2, n2 = labels.get(pid, (v, note))
        out.append({"data": data[pid], "view": v2 or "", "note": n2 or ""})
    return out
