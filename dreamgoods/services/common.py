"""Общие доменные помощники: контекст проекта, чек-листы, учёт расходов, сборка кадров из профиля.
Используются и сервисами (API), и воркерами — поэтому не зависят ни от тех, ни от других."""
from sqlalchemy import select

from ..ai import prompts
from ..core.logs import log
from ..core.settings import effective
from ..core import presets
from ..db.models import (CategoryChecklist, Frame, Generation, GenerationPreset, Organization, Product, ProductProfile,
                         Project, Review, UsageEntry)

LIVE = ("queued", "running", "cancelling", "paused")


# ───────── группы товаров (категория / подраздел из профиля) и модель клиента по группе ─────────

def product_group(s, product):
    """(категория, подраздел) товара из текущего профиля; ("Без профиля", "") если профиля нет."""
    if not product.current_profile_id:
        return "Без профиля", ""
    d = (s.get(ProductProfile, product.current_profile_id).data or {})
    return d.get("category_ru") or "Без категории", d.get("subcategory_ru") or "без подраздела"


def group_keys(cat, sub):
    """Ключи групп от точного к общему: «Обувь / Ботфорты», затем «Обувь»."""
    return [f"{cat} / {sub}", cat] if sub else [cat]


def persona_id_for(s, product, st, rules=None):
    """Какая модель снимает товар: своя у товара → по подразделу → по категории → модель проекта.
    rules — [(persona_id, groups)] моделей клиента (если не передано, читается из базы)."""
    from ..db.models import Persona
    if product.persona_id:
        return product.persona_id, "товар"
    if rules is None:
        project = s.get(Project, product.project_id)
        rules = [(p.id, p.groups or []) for p in s.scalars(select(Persona).where(
            Persona.client_id == project.client_id, Persona.status == "ready")).all()]
    keys = group_keys(*product_group(s, product))
    for key in keys:                      # сначала подраздел, потом категория
        for pid, groups in sorted(rules):
            if key in groups:
                return pid, key
    pid = int(st.get("persona_id") or 0)
    return (pid, "проект") if pid else (0, "")


def preset_of(s, product, project=None):
    """Пресет товара: свой или проекта по умолчанию (None — без пресета)."""
    project = project or s.get(Project, product.project_id)
    pid = product.preset_id or int((project.settings or {}).get("preset_id") or 0)
    p = s.get(GenerationPreset, pid) if pid else None
    return p if p and not p.archived else None


USER_SWITCHES = ("qc_enabled", "qc_autoregen")


def context(s, product):
    """(проект, организация, действующие настройки товара: проект + пресет)."""
    project = s.get(Project, product.project_id)
    org = s.get(Organization, project.client.org_id)
    st = presets.apply(effective(org, project), preset_of(s, product, project))
    # переключатели «ИИ-проверка» и «переделка брака» над списком товаров — явный выбор пользователя:
    # они главнее уровня качества пресета (иначе «Стандарт» включал бы перегенерацию брака вопреки выключателю)
    for k in USER_SWITCHES:
        if k in (project.settings or {}):
            st[k] = project.settings[k]
    if not st.get("qc_enabled") or not st.get("qc_autoregen"):
        st["qc_autoregen"] = bool(st.get("qc_enabled") and st.get("qc_autoregen"))
    return project, org, st


def org_of_project(s, project_id):
    p = s.get(Project, project_id)
    if not p:
        raise LookupError("проект не найден")
    return s.get(Organization, p.client.org_id)


def product_in(s, project_id, product_id):
    p = s.get(Product, int(product_id))
    if not p or p.project_id != project_id:
        raise LookupError("товар не найден")
    return p


def frame_in(s, project_id, frame_id):
    f = s.get(Frame, int(frame_id))
    p = s.get(Product, f.product_id) if f else None
    if not f or not p or p.project_id != project_id:
        raise LookupError("кадр не найден")
    return p, f


def library(s, org_id):
    """Чек-листы категорий: свои у организации поверх общей библиотеки."""
    rows = s.scalars(select(CategoryChecklist).where((CategoryChecklist.org_id.is_(None)) | (CategoryChecklist.org_id == org_id))
                     .order_by(CategoryChecklist.org_id.nullsfirst())).all()
    lib = {}
    for r in rows:
        lib[r.key] = {"name": r.name, "checklist": r.checklist}
    return lib or prompts.DEFAULT_LIBRARY


def review_notes(s, product_id):
    rows = s.execute(select(Review.note_kind, Review.comment).join(Frame, Frame.id == Review.frame_id)
                     .where(Frame.product_id == product_id, Review.comment != "").order_by(Review.id)).all()
    return [(k or "note", c) for k, c in rows]


def checklist_for(s, st, product, org_id):
    prof = s.get(ProductProfile, product.current_profile_id).data if product.current_profile_id else None
    lib = library(s, org_id)
    cat = (prof or {}).get("category") or product.category
    base = (lib.get(cat) or {}).get("checklist") or st.get("qc_checklist") or prompts.DEFAULT_CHECKLIST
    return prompts.checklist_text(base, prof, review_notes(s, product.id))


def write_usage(s, org_id, project_id, product_id, frame_id, trace, ref=""):
    """Переносит накопленные в trace расходы в журнал usage_ledger и списывает их с баланса клиента (с наценкой)."""
    from .billing import charge
    usage = [u for u in trace.usage if not u.get("managed")]
    if usage:
        charge(s, project_id, usage, str(trace))
    for u in usage:
        s.add(UsageEntry(org_id=org_id, project_id=project_id, product_id=product_id, frame_id=frame_id, kind=u["kind"],
                         model=u["model"], provider=u.get("provider", ""), amount_rub=u["cost"], tokens=u["tokens"], ref=ref))
    trace.usage.clear()


def frame_status(qcres):
    if qcres is None:
        return "unchecked"
    return "pass" if qcres["pass"] else "review"


def plan_rows(s, product, prof, plan=None):
    """Кадры товара по действующему пресету: [(промпт, подпись, блок, модель)]."""
    st = context(s, product)[2]
    if plan is None:
        plan = presets.plan_of(st)
    if st.get("plan_mode") == "manual":     # свои методы съёмки: (промпт, подпись, блок, модель)
        return prompts.build_manual(prof, st.get("manual") or [], st.get("market"))
    return [(t, "", "", "") for t in prompts.build_prompts(prof, plan, st.get("market"))]


def frames_differ(s, product, rows, keep_edited=True):
    """Сколько кадров товара разойдётся с планом пресета: (изменятся/добавятся, уже готовых из них — переснимутся)."""
    frames = {f.position: f for f in s.scalars(select(Frame).where(Frame.product_id == product.id, Frame.status != "retired")).all()}
    changed = redo = 0
    for i, (text, title, _, model) in enumerate(rows, 1):
        f = frames.get(i)
        if f is None:
            changed += 1
        elif (f.prompt != text and not (keep_edited and f.prompt_edited)) or (f.title or "") != title or (f.model or "") != model:
            changed += 1
            redo += bool(f.current_generation_id) and f.prompt != text and not (keep_edited and f.prompt_edited)
    extra = [f for pos, f in frames.items() if pos > len(rows)]
    return changed + len(extra), redo + sum(1 for f in extra if f.current_generation_id)


def rebuild_frames(s, product, prof, plan=None, keep_edited=False):
    """Пересобирает промпты кадров из профиля по плану пресета. Если задание кадра поменялось, прежняя картинка
    уходит в историю (не удаляется), а кадр становится «не сгенерирован». Кадры с историей не удаляются.
    keep_edited — не трогать промпты, исправленные вручную (при автоматической сверке перед генерацией)."""
    rows = plan_rows(s, product, prof, plan)
    frames = {f.position: f for f in s.scalars(select(Frame).where(Frame.product_id == product.id)).all()}
    for i, (text, title, _, model) in enumerate(rows, 1):
        f = frames.get(i)
        if f:
            f.title, f.model = title, model
            if keep_edited and f.prompt_edited and f.status != "retired":
                continue
            if f.prompt != text and f.current_generation_id:
                g = s.get(Generation, f.current_generation_id)
                if g:
                    g.outcome = "archived"
                f.current_generation_id, f.status = None, "missing"
            f.prompt, f.prompt_source, f.prompt_edited, f.block = text, "profile", False, prompts.block_of(text)
            if f.status == "retired":
                f.status = "missing"
        else:
            s.add(Frame(product_id=product.id, position=i, prompt=text, prompt_source="profile", block=prompts.block_of(text),
                        title=title, model=model))
    for pos, f in frames.items():
        if pos > len(rows):
            has = s.scalar(select(Generation.id).where(Generation.frame_id == f.id).limit(1))
            if has:      # вне нового плана: скрываем, история генераций сохраняется
                if f.current_generation_id:
                    g = s.get(Generation, f.current_generation_id)
                    if g:
                        g.outcome = "archived"
                f.current_generation_id, f.status = None, "retired"
                log.info("[%s] кадр %02d вне нового плана — скрыт (история сохранена)", product.sku, pos)
            else:
                s.delete(f)
    s.flush()
    return len(rows)

