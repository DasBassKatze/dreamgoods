"""Тарифы клиентов: какой действует, проверка лимитов, подключение и правка условий мастером."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .. import db
from ..core import plans as P
from ..core.logs import log
from ..db.models import Client, GenerationPreset, Organization, Persona, Project, StyleRef, User


class PlanLimit(PermissionError):
    """Действие недоступно на тарифе клиента (ответ 403 с понятным текстом)."""
    status = 403


def _org(s, org_id=None):
    if org_id:
        return s.get(Organization, org_id)
    return s.scalars(select(Organization).order_by(Organization.id)).first()


def limits(s, client):
    """Лимиты тарифа клиента; None — без лимитов (мастер, внутренние кабинеты без оплаты через баланс)."""
    if not P.limited(client):
        return None
    org = _org(s, client.org_id)
    plan = P.all_plans(org.settings if org else {})[P.effective_key(client)]
    return plan


def _next_with(s, client, test):
    """Ближайший тариф выше, где действие доступно — для подсказки «перейдите на …»."""
    org = _org(s, client.org_id)
    allp = P.all_plans(org.settings if org else {})
    cur = P.ORDER.index(P.effective_key(client))
    for k in P.ORDER[cur + 1:]:
        if test(allp[k]):
            return allp[k]["name"]
    return ""


def _deny(s, client, plan, what, test):
    nxt = _next_with(s, client, test)
    tail = f" Доступно на тарифе «{nxt}» и выше — сменить тариф можно на странице «Цены и оплата»." if nxt else ""
    raise PlanLimit(f"На тарифе «{plan['name']}» {what}.{tail}")


# названия для сообщений: (во множественном числе, «не больше N …» в родительном)
NAMES = {"projects": ("проекты", "проектов"), "presets": ("свои пресеты", "своих пресетов"),
         "personas": ("свои модели-люди", "своих моделей"), "styles": ("оформление по примеру", "оформлений"),
         "users": ("дополнительные пользователи", "пользователей")}


def client_of_project(s, project_id):
    p = s.get(Project, project_id)
    return s.get(Client, p.client_id) if p else None


def check_count(s, client, key, current, what=""):
    """Лимит количества: проекты, пресеты, модели, оформление, пользователи."""
    plan = limits(s, client)
    if plan is None or plan.get(key) is None:
        return
    if current >= plan[key]:
        n = plan[key]
        plural, gen = NAMES[key]
        msg = f"можно не больше {n} {gen} (сейчас {current})" if n else f"{plural} недоступны"
        _deny(s, client, plan, msg, lambda p: p.get(key) is None or p[key] > current)


def check_flag(s, client, key, what):
    plan = limits(s, client)
    if plan is not None and not plan.get(key):
        _deny(s, client, plan, f"недоступно: {what}", lambda p: p.get(key))


def check_quality(s, client, quality):
    plan = limits(s, client)
    if plan is not None and quality not in plan["qualities"]:
        name = P.QUALITY_NAMES.get(quality, quality)
        _deny(s, client, plan, f"уровень качества «{name}» недоступен", lambda p: quality in p["qualities"])


# ───────── проверки по объектам ─────────

def check_new_project(s, client):
    n = s.scalar(select(func.count(Project.id)).where(Project.client_id == client.id, Project.archived.is_(False))) or 0
    check_count(s, client, "projects", n, "проект")


def check_new_persona(s, client):
    n = s.scalar(select(func.count(Persona.id)).where(Persona.client_id == client.id, Persona.status != "archived")) or 0
    check_count(s, client, "personas", n, "модель")


def check_new_style(s, client):
    n = s.scalar(select(func.count(StyleRef.id)).where(StyleRef.client_id == client.id, StyleRef.status != "archived")) or 0
    check_count(s, client, "styles", n, "оформление")


def check_new_user(s, client):
    n = s.scalar(select(func.count(User.id)).where(User.client_id == client.id, User.active.is_(True))) or 0
    check_count(s, client, "users", n, "пользователя")


def check_preset(s, client, data, new):
    """Свой пресет клиента: количество и возможности тарифа."""
    if new:
        n = s.scalar(select(func.count(GenerationPreset.id)).where(GenerationPreset.client_id == client.id,
                                                                   GenerationPreset.archived.is_(False))) or 0
        check_count(s, client, "presets", n, "свой пресет")
    check_quality(s, client, data.get("quality") or "standard")
    if (data.get("plan_mode") or "auto") == "manual":
        check_flag(s, client, "manual_plan", "ручной план кадров")
    if any((data.get("block_models") or {}).values()):
        check_flag(s, client, "block_models", "своя модель на блок кадров")
    if ((data.get("market") or {}).get("key")) == "custom":
        check_flag(s, client, "custom_market", "своя площадка")
    if (data.get("strictness") or "normal") != "normal":
        check_flag(s, client, "strictness", "выбор строгости проверки")


def check_storage(s, client, user=None):
    """Место в хранилище: при превышении новые загрузки и генерации не запускаются."""
    plan = limits(s, client)
    if plan is None:
        return
    from .projects import storage_usage
    from ..core.auth import CurrentUser
    u = user or CurrentUser(id=0, org_id=client.org_id, email="", name="", role="user", client_id=client.id)
    used = storage_usage(u)["used"]
    if used >= plan["storage_gb"] * 1024 ** 3:
        _deny(s, client, plan, f"хранилище заполнено ({used / 1024 ** 3:.1f} из {plan['storage_gb']} ГБ): удалите старые "
                               "проекты или перейдите на тариф с большим хранилищем",
              lambda p: p["storage_gb"] > plan["storage_gb"])


def check_generation(s, project_id, product_ids=None):
    """Перед запуском генерации: уровень качества пресетов товаров и место в хранилище."""
    from ..db.models import Product
    from .common import preset_of
    client = client_of_project(s, project_id)
    if limits(s, client) is None:
        return
    project = s.get(Project, project_id)
    q = select(Product).where(Product.project_id == project_id)
    if product_ids:
        q = q.where(Product.id.in_(list(product_ids)))
    seen = set()
    for prod in s.scalars(q).all():
        p = preset_of(s, prod, project)
        quality = p.quality if p else "standard"
        if quality not in seen:
            seen.add(quality)
            check_quality(s, client, quality)
        if p and p.plan_mode == "manual":
            check_flag(s, client, "manual_plan", "ручной план кадров")
        if p and any((p.block_models or {}).values()):
            check_flag(s, client, "block_models", "своя модель на блок кадров")
    check_storage(s, client)


def check_storage_project(project_id):
    with db.session() as s:
        client = client_of_project(s, project_id)
        if client is not None:
            check_storage(s, client)


def check_generation_project(project_id, product_ids=None):
    with db.session() as s:
        check_generation(s, project_id, product_ids)


def parallel_for(s, client_id):
    """Сколько заданий клиента могут идти одновременно (None — без ограничения)."""
    client = s.get(Client, client_id) if client_id else None
    plan = limits(s, client)
    return None if plan is None else plan["parallel"]


# ───────── вид и управление ─────────

def view(client, org_settings=None):
    allp = P.all_plans(org_settings)
    key = P.effective_key(client) if client else None
    return {"key": getattr(client, "plan", "start"), "effective": key, "name": allp[key]["name"] if key else "",
            "until": client.plan_until.isoformat() if client and client.plan_until else None,
            "limited": P.limited(client), "limits": allp[key] if key else None}


def assign(client_id, plan, months=None, until=None):
    """Мастер назначает тариф: на N месяцев от сегодня (или продлевает действующий) либо до даты; «Старт» — без срока."""
    if plan not in P.ORDER:
        raise ValueError("неизвестный тариф")
    with db.session() as s:
        c = s.get(Client, client_id)
        if not c:
            raise LookupError("кабинет не найден")
        _apply(c, plan, months, until)
        log.info("Тариф кабинета «%s»: %s до %s", c.name, plan, c.plan_until)
        return {"plan": c.plan, "until": c.plan_until.isoformat() if c.plan_until else None}


def _apply(c, plan, months=None, until=None):
    now = datetime.now(timezone.utc)
    if plan == "start":
        c.plan, c.plan_until = "start", None
        return
    if until:
        c.plan_until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
    elif months:
        cur = c.plan_until if (c.plan == plan and c.plan_until and c.plan_until > now) else now
        c.plan_until = cur + timedelta(days=round(30.44 * int(months)))
    c.plan = plan


def activate_from_topup(s, client, plan, months):
    """Оплаченная заявка на тариф: тариф подключается или продлевается на оплаченный срок."""
    if plan in P.ORDER and plan != "start" and months:
        _apply(client, plan, months)


def public_plans(org_settings=None):
    """Тарифы для сайта и кабинета."""
    allp = P.all_plans(org_settings)
    return {"plans": [allp[k] | {"popular": k == P.POPULAR} for k in P.ORDER], "features": [list(f) for f in P.FEATURES],
            "common": P.COMMON, "year_pay_months": P.YEAR_PAY_MONTHS, "quality_names": P.QUALITY_NAMES}


def save_overrides(org_id, data):
    with db.session() as s:
        org = s.get(Organization, org_id)
        st = dict(org.settings or {})
        st["plans"] = P.clean_overrides(data)
        org.settings = st
        return P.all_plans(st)
