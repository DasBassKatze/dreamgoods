"""Модерация запрещённого содержания: проверка текстов пользователя, запись в журнал, журнал для мастера."""
from sqlalchemy import select

from .. import db
from ..core import moderation as M
from ..core.logs import log
from ..db.models import Client, ModerationEvent, Product, ProductProfile, Project, User


class Blocked(ValueError):
    """Запрос с запрещённым содержанием — генерация не запускается, ничего не списывается."""
    status = 422


def _ctx(s, project_id=None, product_id=None):
    pr = s.get(Project, project_id) if project_id else None
    if pr is None and product_id:
        p = s.get(Product, product_id)
        pr = s.get(Project, p.project_id) if p else None
    c = s.get(Client, pr.client_id) if pr else None
    return pr, c


def record(source, where, category, excerpt, action="blocked", project_id=None, product_id=None, frame_id=None,
           user_id=None):
    """Запись в журнал модерации (ошибка журнала не должна ломать работу)."""
    try:
        with db.session() as s:
            pr, c = _ctx(s, project_id, product_id)
            s.add(ModerationEvent(org_id=c.org_id if c else None, client_id=c.id if c else None, user_id=user_id,
                                  project_id=pr.id if pr else None, product_id=product_id, frame_id=frame_id,
                                  source=source, where=where[:60], category=category[:30],
                                  excerpt=str(excerpt)[:1000], action=action))
        log.warning("Модерация: %s · %s · %s — %s (%s)", where, M.TITLES.get(category, category), action,
                    str(excerpt)[:120], f"кабинет «{c.name}»" if c else "")
    except Exception as e:
        log.error("Модерация: не удалось записать событие: %s", e)


def guard(where, *texts, project_id=None, product_id=None, frame_id=None, user=None):
    """Текст пользователя: при запрещённом содержании — запись в журнал и отказ с понятным сообщением."""
    hit = M.scan(*texts)
    if not hit:
        return
    cat, found = hit
    record("text", where, cat, found, "blocked", project_id, product_id, frame_id, getattr(user, "id", None))
    raise Blocked(f"Запрос не выполнен: в тексте есть запрещённое в РФ содержание — {M.TITLES.get(cat, cat)} "
                  f"(«{found}»). Уберите это из запроса. Генерация не запускалась, деньги не списаны.")


def guard_products(project_id, product_ids=None):
    """Перед генерацией: товары, на фото которых найдено запрещённое содержание, не снимаются."""
    with db.session() as s:
        q = (select(Product.sku, ProductProfile.data).join(ProductProfile, ProductProfile.id == Product.current_profile_id)
             .where(Product.project_id == project_id))
        if product_ids:
            q = q.where(Product.id.in_(list(product_ids)))
        bad = [sku for sku, data in s.execute(q).all() if str((data or {}).get("prohibited") or "").strip()]
    if bad:
        raise Blocked(f"На фото товара найдено запрещённое в РФ содержание: {', '.join(bad[:5])}"
                      f"{' и др.' if len(bad) > 5 else ''}. Такие товары не снимаются — загрузите другие фото "
                      "(или уберите товар из выбора). Генерация не запускалась, деньги не списаны.")


def listing(org_id, limit=300):
    with db.session() as s:
        rows = s.execute(select(ModerationEvent, Client.name, Project.name, User.email)
                         .outerjoin(Client, Client.id == ModerationEvent.client_id)
                         .outerjoin(Project, Project.id == ModerationEvent.project_id)
                         .outerjoin(User, User.id == ModerationEvent.user_id)
                         .where((ModerationEvent.org_id == org_id) | ModerationEvent.org_id.is_(None))
                         .order_by(ModerationEvent.id.desc()).limit(limit)).all()
        return [{"id": e.id, "created": e.created_at.isoformat() if e.created_at else None, "client": cn or "",
                 "project": pn or "", "user": ue or "", "source": e.source, "where": e.where, "category": e.category,
                 "category_name": M.TITLES.get(e.category, e.category), "excerpt": e.excerpt, "action": e.action,
                 "frame_id": e.frame_id, "product_id": e.product_id} for e, cn, pn, ue in rows]
