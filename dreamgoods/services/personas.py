"""Модели клиента: список, создание, фото (свои или сгенерированный образ), выбор образа, привязка к проекту и товару.

Модель принадлежит клиенту, а не проекту: одна и та же «лицо магазина» используется во всех его проектах
(и будет видна клиенту в личном кабинете)."""
from sqlalchemy import func, select

from .. import db
from ..core import storage
from ..core.events import say
from ..ai.persona import STYLE_KEYS
from ..core.logs import log
from ..db.models import Job, Persona, PersonaPhoto, Product, Project
from ..workers.queue import enqueue
from .common import LIVE, org_of_project, persona_id_for, product_group, product_in

PHOTO_KINDS = ("main", "photo", "sheet", "candidate")


def _project(s, project_id):
    p = s.get(Project, project_id)
    if not p:
        raise LookupError("проект не найден")
    return p


def _persona(s, project_id, persona_id):
    """Модель, доступная проекту (того же клиента)."""
    project = _project(s, project_id)
    p = s.get(Persona, int(persona_id))
    if not p or p.client_id != project.client_id or p.status == "archived":
        raise LookupError("модель не найдена")
    return p


def _jobs(s, project_id):
    """Последнее активное или ошибочное задание по каждой модели."""
    out = {}
    for j in s.scalars(select(Job).where(Job.kind == "persona", Job.project_id == project_id,
                                         Job.status.in_(LIVE + ("error",))).order_by(Job.id)).all():
        out[int((j.payload or {}).get("persona_id") or 0)] = j
    return out


def listing(project_id):
    with db.session() as s:
        project = _project(s, project_id)
        default = int((project.settings or {}).get("persona_id") or 0)
        personas = s.scalars(select(Persona).where(Persona.client_id == project.client_id, Persona.status != "archived")
                             .order_by(Persona.id)).all()
        ids = [p.id for p in personas]
        photos = s.scalars(select(PersonaPhoto).where(PersonaPhoto.persona_id.in_(ids))
                           .order_by(PersonaPhoto.position, PersonaPhoto.id)).all() if ids else []
        used = dict(s.execute(select(Product.persona_id, func.count(Product.id))
                              .where(Product.project_id == project_id, Product.persona_id.in_(ids))
                              .group_by(Product.persona_id)).all()) if ids else {}
        jobs = _jobs(s, project_id)
        # какие товары проекта снимаются на какой модели (с учётом групп) и дерево групп для выбора
        rules = [(p.id, p.groups or []) for p in personas if p.status == "ready"]
        st = {"persona_id": default}
        effective, tree = {}, {}
        for pr in s.scalars(select(Product).where(Product.project_id == project_id)).all():
            pid, via = persona_id_for(s, pr, st, rules)
            if pid:
                e = effective.setdefault(pid, {"total": 0, "own": 0, "groups": 0, "project": 0})
                e["total"] += 1
                e["own" if via == "товар" else "project" if via == "проект" else "groups"] += 1
            cat, sc = product_group(s, pr)
            node = tree.setdefault(cat, {"count": 0, "subs": {}})
            node["count"] += 1
            if sc:
                node["subs"][sc] = node["subs"].get(sc, 0) + 1
        claimed = {}
        for p in personas:
            for g in p.groups or []:
                claimed.setdefault(g, []).append(p.name)
        by = {}
        for ph in photos:
            by.setdefault(ph.persona_id, []).append(
                {"id": ph.id, "asset": str(ph.asset_id), "kind": ph.kind, "view": ph.view, "cost": round(ph.cost_rub, 2),
                 "title": (ph.spec or {}).get("name_ru", "")})
        out = []
        for p in personas:
            j = jobs.get(p.id)
            out.append({"id": p.id, "name": p.name, "brief": p.brief, "description": p.description, "style": p.style or {},
                        "source": p.source,
                        "status": p.status, "consent": p.consent, "photos": by.get(p.id, []),
                        "products": used.get(p.id, 0), "is_default": p.id == default, "groups": list(p.groups or []),
                        "usage": effective.get(p.id, {"total": 0, "own": 0, "groups": 0, "project": 0}),
                        "job": None if not j else {"state": "error" if j.status == "error" else "running",
                                                   "note": j.note, "error": j.error, "mode": (j.payload or {}).get("mode")}})
        return {"personas": out, "default_id": default if default in ids else 0,
                "groups": [{"name": c, "count": n["count"], "subs": [{"name": k, "count": v} for k, v in sorted(n["subs"].items())]}
                           for c, n in sorted(tree.items())],
                "conflicts": {g: names for g, names in claimed.items() if len(names) > 1}}


def create(project_id, name, brief, source):
    with db.session() as s:
        project = _project(s, project_id)
        from .plans import check_new_persona
        check_new_persona(s, project.client)
        p = Persona(client_id=project.client_id, name=(name or "").strip()[:120] or "Новая модель", brief=(brief or "").strip(),
                    source="upload" if source == "upload" else "generated", status="draft")
        s.add(p)
        s.flush()
        log.info("Модель клиента «%s» создана (%s)", p.name, p.source)
        return p.id


def update(project_id, persona_id, values):
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        for k in ("name", "brief", "description"):
            if k in values and values[k] is not None:
                setattr(p, k, str(values[k]).strip()[:120] if k == "name" else str(values[k]).strip())
        if isinstance(values.get("style"), dict):
            p.style = {k: str(values["style"].get(k) or "").strip() for k in STYLE_KEYS}
        if isinstance(values.get("groups"), list):
            p.groups = sorted({str(g).strip()[:160] for g in values["groups"] if str(g).strip()})[:50]
        if "consent" in values and values["consent"] is not None:
            p.consent = bool(values["consent"])
        if p.status == "draft" and p.description and _has_main(s, p.id):
            p.status = "ready"


def archive(project_id, persona_id):
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        p.status = "archived"
        for pr in s.scalars(select(Project).where(Project.client_id == p.client_id)).all():
            if int((pr.settings or {}).get("persona_id") or 0) == p.id:
                pr.settings = {**pr.settings, "persona_id": 0}
        s.query(Product).filter(Product.persona_id == p.id).update({Product.persona_id: None})
        log.info("Модель «%s» убрана в архив", p.name)


def _has_main(s, pid):
    return bool(s.scalar(select(func.count(PersonaPhoto.id)).where(PersonaPhoto.persona_id == pid,
                                                                    PersonaPhoto.kind.in_(("main", "photo")))))


def _enqueue(s, project_id, persona_id, mode, **extra):
    busy = s.scalar(select(Job.id).where(Job.kind == "persona", Job.status.in_(LIVE),
                                         Job.payload["persona_id"].as_integer() == persona_id))
    if busy:
        raise ValueError("по этой модели уже идёт задание — дождитесь окончания")
    return enqueue(s, "persona", project_id, payload={"persona_id": persona_id, "mode": mode, **extra}, priority=15)


def upload_photo(project_id, persona_id, data, filename):
    """Фото модели от клиента. Нужно подтверждённое согласие человека на использование фото."""
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        if not p.consent:
            raise ValueError("Подтвердите, что у вас есть согласие человека на использование его фото")
        org = org_of_project(s, project_id)
        a = storage.put(s, org.id, data, "persona", filename)
        if not (a.mime or "").startswith("image/"):
            raise ValueError("это не картинка")
        pos = (s.scalar(select(func.max(PersonaPhoto.position)).where(PersonaPhoto.persona_id == p.id)) or 0) + 1
        first = not _has_main(s, p.id)
        s.add(PersonaPhoto(persona_id=p.id, asset_id=a.id, kind="main" if first else "photo", position=pos))
        p.source = "upload"
        return {"ok": True}


MAX_REFS = 4


def upload_ref(project_id, persona_id, data, filename):
    """Референс образа для генерации модели: пример причёски, макияжа, одежды, настроения.
    Лицо с референса не копируется — модель получается новым человеком, поэтому согласие не нужно."""
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        n = s.scalar(select(func.count(PersonaPhoto.id)).where(PersonaPhoto.persona_id == p.id, PersonaPhoto.kind == "ref"))
        if n >= MAX_REFS:
            raise ValueError(f"референсов образа не больше {MAX_REFS} — удалите лишний")
        org = org_of_project(s, project_id)
        a = storage.put(s, org.id, data, "persona", filename)
        if not (a.mime or "").startswith("image/"):
            raise ValueError("это не картинка")
        pos = (s.scalar(select(func.max(PersonaPhoto.position)).where(PersonaPhoto.persona_id == p.id)) or 0) + 1
        s.add(PersonaPhoto(persona_id=p.id, asset_id=a.id, kind="ref", position=pos))
        return {"ok": True}


def describe(project_id, persona_id):
    """ИИ описывает внешность по фото (после загрузки)."""
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        if not _has_main(s, p.id):
            raise ValueError("сначала загрузите фото модели")
        _enqueue(s, project_id, p.id, "describe")


def delete_photo(project_id, persona_id, photo_id):
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        ph = s.get(PersonaPhoto, int(photo_id))
        if not ph or ph.persona_id != p.id:
            raise LookupError("фото не найдено")
        was_main = ph.kind == "main"
        s.delete(ph)
        s.flush()
        if was_main:      # основным становится следующее фото
            nxt = s.scalars(select(PersonaPhoto).where(PersonaPhoto.persona_id == p.id, PersonaPhoto.kind == "photo")
                            .order_by(PersonaPhoto.position)).first()
            if nxt:
                nxt.kind = "main"
            elif not _has_main(s, p.id):
                p.status = "draft"


def generate_candidates(project_id, persona_id, count, brief=None):
    """Варианты образа по пожеланиям (новые пожелания, если переданы, сохраняются)."""
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        if brief is not None and brief.strip():
            p.brief = brief.strip()
        if not (p.brief or p.description):
            raise ValueError("опишите, какой должна быть модель")
        _enqueue(s, project_id, p.id, "candidates", count=max(1, min(4, int(count or 2))))
        name = p.name
    say("info", f"👤 Модель «{name}»: генерирую варианты образа ({count})", project_id)


def edit(project_id, persona_id, request, count):
    """Изменение внешности выбранной модели: «волосы рыжие», «добавить пирсинг», «макияж ярче»…"""
    if not (request or "").strip():
        raise ValueError("напишите, что изменить")
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        if not s.scalar(select(PersonaPhoto.id).where(PersonaPhoto.persona_id == p.id, PersonaPhoto.kind == "main")):
            raise ValueError("сначала выберите основной образ")
        _enqueue(s, project_id, p.id, "edit", count=max(1, min(4, int(count or 2))), request=request.strip())
        name = p.name
    say("info", f"👤 Модель «{name}»: меняю внешность — «{request.strip()[:80]}»", project_id)


def choose(project_id, persona_id, photo_id):
    """Выбранный вариант становится основным образом. Остальные варианты и ракурсы прошлого образа убираются."""
    if not photo_id:
        raise ValueError("не указано фото")
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        ph = s.get(PersonaPhoto, int(photo_id))
        if not ph or ph.persona_id != p.id:
            raise LookupError("фото не найдено")
        for other in s.scalars(select(PersonaPhoto).where(PersonaPhoto.persona_id == p.id, PersonaPhoto.id != ph.id)).all():
            if other.kind in ("candidate", "sheet", "main"):
                s.delete(other)
        ph.kind, ph.position = "main", 0
        spec = ph.spec or {}
        if spec.get("appearance"):          # паспорт выбранного варианта становится паспортом модели
            p.description = spec["appearance"]
            p.style = spec.get("style") or {}
        if p.description:
            p.status = "ready"
        name = p.name
    log.info("Модель «%s»: выбран основной образ", name)


def make_sheet(project_id, persona_id):
    with db.session() as s:
        p = _persona(s, project_id, persona_id)
        if not s.scalar(select(PersonaPhoto.id).where(PersonaPhoto.persona_id == p.id, PersonaPhoto.kind == "main")):
            raise ValueError("сначала выберите основной образ")
        for old in s.scalars(select(PersonaPhoto).where(PersonaPhoto.persona_id == p.id, PersonaPhoto.kind == "sheet")).all():
            s.delete(old)
        _enqueue(s, project_id, p.id, "sheet")
        name = p.name
    say("info", f"👤 Модель «{name}»: делаю дополнительные ракурсы", project_id)


def set_project_default(project_id, persona_id):
    with db.session() as s:
        project = _project(s, project_id)
        if persona_id:
            p = _persona(s, project_id, persona_id)
            if p.status != "ready":
                raise ValueError("модель ещё не готова: нужен основной образ и описание внешности")
        project.settings = {**(project.settings or {}), "persona_id": int(persona_id or 0)}


def set_product_persona(project_id, product_id, persona_id):
    with db.session() as s:
        pr = product_in(s, project_id, product_id)
        if persona_id:
            _persona(s, project_id, persona_id)
        pr.persona_id = int(persona_id) if persona_id else None
