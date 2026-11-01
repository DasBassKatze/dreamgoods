"""Задание «persona»: модель клиента.
  describe   — ИИ составляет паспорт образа (внешность + стиль) по загруженным фото;
  candidates — по пожеланиям клиента ИИ пишет N разных паспортов и по каждому генерирует образ «для примерки»;
  edit       — изменение внешности выбранной модели: ИИ правит паспорт по запросу, генератор меняет основное фото;
  sheet      — дополнительные ракурсы выбранного образа (портрет, ¾, профиль) — точнее держится лицо и фигура.
Клиент выбирает картинку; паспорт выбранного варианта становится паспортом модели.
"""
import time

from sqlalchemy import func, select

from .. import db
from ..ai import persona as P
from ..ai import polza
from ..ai.images import ref_payload
from ..core import storage
from ..core.events import say
from ..core.logs import Trace, log
from ..core.settings import effective
from ..db.models import Job, Organization, Persona, PersonaPhoto, Project
from ..services.common import write_usage
from .queue import cancelled, set_note


def _context(job_id):
    with db.session() as s:
        job = s.get(Job, job_id)
        project = s.get(Project, job.project_id)
        org = s.get(Organization, project.client.org_id)
        return dict(job.payload or {}), org.id, project.id, effective(org, project)


def handle(job_id):
    payload, org_id, project_id, st = _context(job_id)
    pid, mode = int(payload["persona_id"]), payload.get("mode", "describe")
    with db.session() as s:
        name = s.get(Persona, pid).name
    ctx = dict(job_id=job_id, pid=pid, org_id=org_id, project_id=project_id, st=st, trace=Trace(f"[модель «{name}»]"))
    count = max(1, min(4, int(payload.get("count") or 2)))
    if mode == "describe":
        _describe(**ctx)
    elif mode == "candidates":
        _candidates(**ctx, count=count)
    elif mode == "edit":
        _edit(**ctx, count=count, request=str(payload.get("request") or ""))
    elif mode == "sheet":
        _sheet(**ctx, views=payload.get("views") or list(P.SHEET_VIEWS))
    else:
        raise RuntimeError(f"неизвестный режим: {mode}")


def _photos(s, pid, kinds):
    return s.scalars(select(PersonaPhoto).where(PersonaPhoto.persona_id == pid, PersonaPhoto.kind.in_(kinds))
                     .order_by(PersonaPhoto.position, PersonaPhoto.id)).all()


def _need_key(st):
    if not st.get("api_key"):
        raise RuntimeError("не указан API-ключ Polza (Настройки)")


def _describe(job_id, pid, org_id, project_id, st, trace):
    set_note(job_id, "описание внешности и стиля")
    with db.session() as s:
        assets = [p.asset for p in _photos(s, pid, ("photo", "main", "sheet"))]
    if not assets:
        raise RuntimeError("у модели нет фото")
    spec, cost = P.describe(st, [storage.get(a) for a in assets], trace)
    with db.session() as s:
        p = s.get(Persona, pid)
        p.description, p.style = spec["appearance"], spec["style"]
        main = _photos(s, pid, ("main",))
        if main:
            main[0].spec = spec
        if p.status == "draft" and p.description:
            p.status = "ready"
        name = p.name
        write_usage(s, org_id, project_id, None, None, trace, f"persona:{pid}")
    say("ok", f"👤 Модель «{name}»: внешность и стиль описаны · {cost:.2f} ₽", project_id)


def _generate(st, prompt, refs, trace):
    """Одна картинка у Polza. Возвращает (байты, стоимость)."""
    data = polza.generate(st, st["api_key"], prompt, refs, str(trace))
    img = polza.extract_image(data)
    if not img:
        raise RuntimeError("в ответе Polza нет картинки")
    usage = data.get("usage") or {}
    cost = polza._num(usage.get("cost_rub")) or polza._num(usage.get("cost")) or 0.0
    trace.add("persona", st["model"], cost, provider=data.get("provider", ""), operation_id=data.get("_billing_operation"))
    return img, cost


def _save(pid, org_id, project_id, img, kind, view, cost, trace, name, spec=None):
    with db.session() as s:
        pos = (s.scalar(select(func.max(PersonaPhoto.position)).where(PersonaPhoto.persona_id == pid)) or 0) + 1
        a = storage.put(s, org_id, img, "persona", name)
        s.add(PersonaPhoto(persona_id=pid, asset_id=a.id, kind=kind, view=view, position=pos, cost_rub=cost, spec=spec or {}))
        write_usage(s, org_id, project_id, None, None, trace, f"persona:{pid}")


def _variants(job_id, pid, org_id, project_id, st, trace, specs, make_prompt, refs, label):
    """Генерирует по картинке на каждый паспорт и сохраняет как варианты для выбора."""
    gst = dict(st, aspect="3:4")
    total, made = 0.0, 0
    for i, spec in enumerate(specs, 1):
        if i > 1 and cancelled(job_id):
            break
        set_note(job_id, f"{label} {i}/{len(specs)}")
        t0 = time.time()
        img, cost = _generate(gst, make_prompt(spec), refs, trace)
        _save(pid, org_id, project_id, img, "candidate", "full front", cost, trace, f"persona{pid}_{label}{i}.png", spec)
        log.info("%s %s %d/%d · %.2f ₽ · %.0f с · %s", trace, label, i, len(specs), cost, time.time() - t0, spec.get("name_ru"))
        total += cost
        made += 1
    return made, total


def _candidates(job_id, pid, org_id, project_id, st, trace, count):
    _need_key(st)
    with db.session() as s:
        p = s.get(Persona, pid)
        brief = p.brief or p.description or "молодая женщина, естественная внешность"
    set_note(job_id, "ИИ продумывает образы")
    specs, _ = P.specs_from_brief(st, brief, count, trace)
    with db.session() as s:
        p = s.get(Persona, pid)
        if specs[0]["name_ru"] and p.name.startswith("Новая модель"):
            p.name = specs[0]["name_ru"]
        name = p.name
        write_usage(s, org_id, project_id, None, None, trace, f"persona:{pid}")
    made, total = _variants(job_id, pid, org_id, project_id, st, trace, specs, P.candidate_prompt, [], "вариант")
    say("ok", f"👤 Модель «{name}»: готово вариантов образа {made} · {total:.2f} ₽ — выберите один", project_id)


def current_spec(s, p):
    """Паспорт выбранной модели: внешность и стиль из модели + наряд и фон основного фото."""
    main = _photos(s, p.id, ("main",))
    look = ((main[0].spec or {}).get("look") if main else None) or {}
    return {"name_ru": p.name, "appearance": p.description, "style": dict(p.style or {}), "look": look}


def _edit(job_id, pid, org_id, project_id, st, trace, count, request):
    _need_key(st)
    if not request.strip():
        raise RuntimeError("не указано, что изменить")
    with db.session() as s:
        p = s.get(Persona, pid)
        main = _photos(s, pid, ("main",))
        if not main:
            raise RuntimeError("сначала выберите основной образ")
        ref = storage.get(main[0].asset)
        cur, name = current_spec(s, p), p.name
    set_note(job_id, "ИИ правит описание образа")
    specs, _ = P.specs_for_edit(st, cur, request, count, trace)
    with db.session() as s:
        write_usage(s, org_id, project_id, None, None, trace, f"persona:{pid}")
    refs = [ref_payload(ref, int(st.get("ref_side") or 1536))]
    made, total = _variants(job_id, pid, org_id, project_id, st, trace, specs, P.edit_prompt, refs, "изменение")
    say("ok", f"👤 Модель «{name}»: вариантов с изменениями {made} · {total:.2f} ₽ — выберите один", project_id)


def _sheet(job_id, pid, org_id, project_id, st, trace, views):
    _need_key(st)
    with db.session() as s:
        main = _photos(s, pid, ("main",))
        if not main:
            raise RuntimeError("сначала выберите основной образ")
        ref, spec = storage.get(main[0].asset), dict(main[0].spec or {})
        name = s.get(Persona, pid).name
    gst = dict(st, aspect="3:4")
    refs = [ref_payload(ref, int(st.get("ref_side") or 1536))]
    views = [v for v in views if v in P.SHEET_VIEWS]
    total, made = 0.0, 0
    for i, view in enumerate(views, 1):
        if i > 1 and cancelled(job_id):
            break
        set_note(job_id, f"ракурс {i}/{len(views)}")
        img, cost = _generate(gst, P.sheet_prompt(view), refs, trace)
        _save(pid, org_id, project_id, img, "sheet", view, cost, trace, f"persona{pid}_{view}.png", spec)
        total += cost
        made += 1
    say("ok", f"👤 Модель «{name}»: готово ракурсов {made} · {total:.2f} ₽", project_id)

