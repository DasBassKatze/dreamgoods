"""Пул ключей Polza: какой ключ использует клиент.

1. Ключ, закреплённый за клиентом (если включён).
2. Иначе — один из общих ключей пула. Выбор стабильный (по номеру клиента), чтобы задачи клиента всегда
   шли с одного ключа: опрос статуса и дозагрузка результата должны идти тем же ключом, что и создание задачи.
3. Иначе — ключ из настроек (POLZA_API_KEY / технические настройки), как раньше.
"""
from sqlalchemy import select

from ..db.models import Client, PolzaKey


def pool(s, org_id):
    return s.scalars(select(PolzaKey).where(PolzaKey.org_id == org_id, PolzaKey.active.is_(True), PolzaKey.shared.is_(True))
                     .order_by(PolzaKey.id)).all()


def for_client(s, client_id, org_id):
    """→ (секрет, id ключа) или ("", None)."""
    c = s.get(Client, client_id) if client_id else None
    if c and c.key_id:
        k = s.get(PolzaKey, c.key_id)
        if k and k.active:
            return k.secret, k.id
    keys = pool(s, org_id)
    if keys:
        k = keys[(client_id or 0) % len(keys)]
        return k.secret, k.id
    return "", None


def all_secrets(s, org_id):
    """Все включённые ключи (для дозагрузки результата, если пул менялся после отправки задачи)."""
    return [k.secret for k in s.scalars(select(PolzaKey).where(PolzaKey.org_id == org_id, PolzaKey.active.is_(True))).all()]


def mask(secret):
    return f"{secret[:6]}…{secret[-4:]}" if secret and len(secret) > 12 else "••••"
