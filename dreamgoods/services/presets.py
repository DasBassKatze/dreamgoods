"""Пресеты генерации: список, создание, правка, применение к товарам (выбранным, по категориям или ко всем).

Применение: товарам ставится пресет, затем промпты кадров пересобираются по его плану.
Если в профиле товара хватает кадров нужных видов — пересборка сразу и бесплатно; если нет (например, в плане
появились «детали» или «лайфстайл») — ИИ заново составляет профиль по фото (≈ 0,04 ₽ за товар)."""
from sqlalchemy import func, select

from .. import db
from ..core import presets as P
from ..core.events import say
from ..core.logs import log
from ..db.models import GenerationPreset, Job, Product, ProductPhoto, ProductProfile, Project
from ..workers.queue import enqueue
from .common import LIVE, context, org_of_project, rebuild_frames


def seed(org_id):
    """Готовые пресеты для новой организации."""
    with db.session() as s:
        if s.scalar(select(func.count(GenerationPreset.id)).where(GenerationPreset.org_id == org_id)):
            return
        for p in P.DEFAULT_PRESETS:
            s.add(GenerationPreset(org_id=org_id, name=p["name"], description=p["description"], quality=p["quality"],
                                   plan=P.clean_plan(p["plan"]), custom={}, market=P.clean_market(p.get("market")),
                                   strictness=p.get("strictness", "normal")))
        log.info("Пресеты генерации: добавлены готовые (%d)", len(P.DEFAULT_PRESETS))


def _get(s, project_id, preset_id, edit=False, master=False):
    """Пресет, доступный проекту: общий (client_id=None, от мастера) или свой у клиента проекта.
    Менять общие пресеты может только мастер."""
    org = org_of_project(s, project_id)
    project = s.get(Project, project_id)
    p = s.get(GenerationPreset, int(preset_id))
    if not p or p.org_id != org.id or p.archived or p.client_id not in (None, project.client_id):
        raise LookupError("пресет не найден")
    if edit and p.client_id is None and not master:
        raise PermissionError("это общий пресет сервиса — его меняет администратор. Создайте свой пресет на его основе")
    return p


def _view(p, default_id, used):
    return {"id": p.id, "name": p.name, "shared": p.client_id is None, "description": p.description, "quality": p.quality, "custom": p.custom or {},
            "plan": P.clean_plan(p.plan), "total": P.preset_total(p), "is_default": p.id == default_id,
            "plan_mode": p.plan_mode or "auto", "manual": P.clean_manual(p.manual), "block_models": P.clean_block_models(p.block_models),
            "products": used.get(p.id, 0), "market": P.clean_market(p.market), "strictness": p.strictness or "normal"}


def listing(project_id):
    with db.session() as s:
        org = org_of_project(s, project_id)
        project = s.get(Project, project_id)
        default = int((project.settings or {}).get("preset_id") or 0)
        rows = s.scalars(select(GenerationPreset).where(GenerationPreset.org_id == org.id, GenerationPreset.archived.is_(False),
                                                        (GenerationPreset.client_id.is_(None))
                                                        | (GenerationPreset.client_id == project.client_id))
                         .order_by(GenerationPreset.client_id.nullsfirst(), GenerationPreset.id)).all()
        used = dict(s.execute(select(Product.preset_id, func.count(Product.id)).where(Product.project_id == project_id,
                                                                                      Product.preset_id.is_not(None))
                              .group_by(Product.preset_id)).all())
        tree, no_sub = {}, 0          # категория → {подраздел: товаров}
        for (data,) in s.execute(select(ProductProfile.data).join(Product, Product.current_profile_id == ProductProfile.id)
                                 .where(Product.project_id == project_id)).all():
            c = (data or {}).get("category_ru") or "Без категории"
            sc = (data or {}).get("subcategory_ru") or ""
            no_sub += not sc
            tree.setdefault(c, {})
            tree[c][sc or "без подраздела"] = tree[c].get(sc or "без подраздела", 0) + 1
        cats = sorted((c, sum(v.values()), v) for c, v in tree.items())
        no_profile = s.scalar(select(func.count(Product.id)).where(Product.project_id == project_id,
                                                                    Product.current_profile_id.is_(None)))
        return {"presets": [_view(p, default, used) for p in rows], "default_id": default if any(p.id == default for p in rows) else 0,
                "quality": [{"key": k, "name": v["name"], "hint": v["hint"], "settings": v["settings"]} for k, v in P.QUALITY.items()],
                "blocks": [{"key": k, "name": v[0], "max": v[2]} for k, v in P.BLOCKS.items()],
                "categories": [{"name": c, "count": n, "subs": [{"name": k, "count": m} for k, m in sorted(subs.items())]}
                               for c, n, subs in cats]
                + ([{"name": "Без профиля", "count": no_profile, "subs": []}] if no_profile else []),
                "no_subcategory": no_sub,
                "markets": [{"key": k, **{x: v[x] for x in ("name", "aspect", "min_side", "hint", "cover_bg", "cover_fill", "cover_extra")}}
                            for k, v in P.MARKETS.items()],
                "aspects": list(P.ASPECTS), "aspect_names": P.ASPECT_NAMES,
                "strictness": [{"key": k, **v} for k, v in P.STRICTNESS.items()],
                "model_stats": model_stats(s, org.id)}


def model_stats(s, org_id):
    """Как модели работают по блокам кадров (по всей организации): кадров, % прошедших проверку с 1-й попытки,
    средняя цена генерации. Подсказка, где можно взять модель подешевле без потери качества."""
    from ..db.models import Client, Frame, Generation, QCCheck
    rows = s.execute(select(Frame.block, Generation.model, Generation.attempt, Generation.cost_rub, QCCheck.passed)
                     .join(Frame, Frame.id == Generation.frame_id)
                     .join(Product, Product.id == Frame.product_id).join(Project, Project.id == Product.project_id)
                     .join(Client, Client.id == Project.client_id)
                     .outerjoin(QCCheck, (QCCheck.generation_id == Generation.id) & (QCCheck.source == "gen"))
                     .where(Generation.status == "ok", Client.org_id == org_id)).all()
    agg = {}
    for block, model, attempt, cost, passed in rows:
        key = (P.BLOCK_OF_PROMPT.get(block or "", ""), model or "?")
        a = agg.setdefault(key, {"n": 0, "cost": 0.0, "first": 0, "first_ok": 0})
        a["n"] += 1
        a["cost"] += float(cost or 0)
        if attempt == 1 and passed is not None:
            a["first"] += 1
            a["first_ok"] += bool(passed)
    return [{"block": b, "model": m, "n": a["n"], "avg_cost": round(a["cost"] / a["n"], 2) if a["n"] else 0,
             "first_pass": round(a["first_ok"] / a["first"] * 100) if a["first"] else None}
            for (b, m), a in sorted(agg.items()) if b]


def save(project_id, preset_id, data, master=False):
    """Создать (preset_id=None) или изменить пресет. Пресет пользователя — свой у его клиента;
    мастер создаёт общие пресеты (видны всем)."""
    quality = data.get("quality") if data.get("quality") in P.QUALITY else "standard"
    with db.session() as s:
        if preset_id:
            p = _get(s, project_id, preset_id, edit=True, master=master)
        else:
            shared = master and data.get("shared", True) is not False
            p = GenerationPreset(org_id=org_of_project(s, project_id).id,
                                 client_id=None if shared else s.get(Project, project_id).client_id)
            s.add(p)
        p.name = (str(data.get("name") or "").strip() or "Новый пресет")[:120]
        p.description = str(data.get("description") or "").strip()
        p.quality = quality
        # основная модель пресета задаётся на любом уровне качества; остальные свои значения — только у «Своего»
        p.custom = P.clean_custom(data.get("custom")) if quality == "custom" else P.clean_main_model(data.get("custom"))
        p.plan = P.clean_plan(data.get("plan"))
        p.plan_mode = "manual" if data.get("plan_mode") == "manual" else "auto"
        p.manual = P.clean_manual(data.get("manual"))
        p.block_models = P.clean_block_models(data.get("block_models"))
        p.market = P.clean_market(data.get("market"))
        p.strictness = data.get("strictness") if data.get("strictness") in P.STRICTNESS else "normal"
        cover = p.market.get("cover") and p.market["key"] != "none"
        if cover and p.plan_mode == "manual" and p.manual and p.manual[0]["block"] != "studio":
            raise ValueError("для обложки площадки первым методом съёмки должен идти тип «товар» — он станет обложкой")
        if cover and p.plan_mode == "auto" and not p.plan["studio"]:
            raise ValueError("для обложки площадки нужен хотя бы один кадр «на белом фоне» — первый станет обложкой")
        if p.plan_mode == "manual" and not p.manual:
            raise ValueError("в ручном плане нет ни одного метода съёмки с промптом")
        if p.plan_mode == "auto" and not P.total(p.plan):
            raise ValueError("в плане должен быть хотя бы один кадр")
        s.flush()
        return p.id


def archive(project_id, preset_id, master=False):
    with db.session() as s:
        p = _get(s, project_id, preset_id, edit=True, master=master)
        p.archived = True
        s.query(Product).filter(Product.preset_id == p.id).update({Product.preset_id: None})
        for pr in s.scalars(select(Project)).all():
            if int((pr.settings or {}).get("preset_id") or 0) == p.id:
                pr.settings = {**pr.settings, "preset_id": 0}


def _targets(s, project_id, product_ids, categories, everything):
    q = select(Product).where(Product.project_id == project_id)
    products = s.scalars(q).all()
    if everything:
        return products
    want = set(map(int, product_ids or []))
    cats = set(categories or [])
    profiles = {pp.id: pp for pp in s.scalars(select(ProductProfile).where(ProductProfile.id.in_(
        [p.current_profile_id for p in products if p.current_profile_id]))).all()}
    out = []
    for p in products:
        pp = profiles.get(p.current_profile_id)
        cat = ((pp.data or {}).get("category_ru") or "Без категории") if pp else "Без профиля"
        sc = ((pp.data or {}).get("subcategory_ru") or "без подраздела") if pp else ""
        if p.id in want or cat in cats or f"{cat} / {sc}" in cats:
            out.append(p)
    return out


def detect_subcategories(project_id):
    """ИИ проставит подразделы товарам, у которых их нет (одно задание на проект)."""
    from ..db.models import Job
    from .common import LIVE
    with db.session() as s:
        if s.scalar(select(Job.id).where(Job.project_id == project_id, Job.kind == "subcats", Job.status.in_(LIVE))):
            raise ValueError("подразделы уже определяются")
        enqueue(s, "subcats", project_id, payload={}, priority=15)


def _needs_profile(prof, plan):
    """Хватает ли в профиле кадров каждого вида под план."""
    if not prof:
        return True
    return any(len(prof.get(P.BLOCKS[k][1]) or []) < n for k, n in plan.items())


def apply(project_id, preset_id, product_ids=None, categories=None, everything=False, make_default=False,
          rebuild=True, dry_run=False):
    """Назначает пресет товарам и пересобирает их кадры. dry_run — только посчитать, что произойдёт."""
    with db.session() as s:
        preset = _get(s, project_id, preset_id) if preset_id else None
        manual = preset is not None and preset.plan_mode == "manual"
        plan = (P.manual_plan(P.clean_manual(preset.manual)) if manual else P.clean_plan(preset.plan)) if preset else None
        targets = _targets(s, project_id, product_ids, categories, everything)
        instant, need_ai = [], []
        for p in targets:
            prof = s.get(ProductProfile, p.current_profile_id).data if p.current_profile_id else None
            eff_plan = plan or _fallback_plan(s, project_id)
            # ручной план берёт из профиля только описание товара — новый профиль нужен, лишь если его нет
            (need_ai if (not prof if manual else _needs_profile(prof, eff_plan)) else instant).append(p)
        summary = {"products": len(targets), "instant": len(instant), "need_profile": len(need_ai),
                   "frames": P.total(plan) if plan else None}
        if dry_run:
            return summary
        for p in targets:
            p.preset_id = preset.id if preset else None
        if make_default:
            project = s.get(Project, project_id)
            project.settings = {**(project.settings or {}), "preset_id": preset.id if preset else 0}
        s.flush()
        rebuilt = queued = 0
        if rebuild:
            for p in instant:
                prof = s.get(ProductProfile, p.current_profile_id).data
                rebuild_frames(s, p, prof)
                rebuilt += 1
            for p in need_ai:
                if enqueue(s, "profile", project_id, product_id=p.id, payload={"build": True}, priority=20):
                    queued += 1
        name = preset.name if preset else "без пресета"
    summary.update(rebuilt=rebuilt, queued=queued)
    say("ok", f"🎛 Пресет «{name}» назначен товарам: {len(targets)}"
        + (f"; промпты пересобраны сразу: {rebuilt}" if rebuilt else "")
        + (f"; ИИ составляет профиль заново: {queued}" if queued else ""), project_id)
    return summary


def sync_for_generation(project_id, product_ids=None, dry_run=False, limit=0):
    """Перед генерацией кадры товаров приводятся к действующему пресету (свой у товара или пресет проекта).
    Изменившиеся кадры пересобираются (готовая картинка уходит в историю); если в профиле не хватает
    кадров нужного вида — ИИ составляет профиль заново, а генерация начнётся сама, когда промпты будут готовы.
    dry_run — посчитать то же самое и откатить: сколько кадров встанет в очередь, сколько переснимется."""
    from .common import frames_differ, plan_rows
    from .frames import missing_frames
    out = {"products": 0, "frames": 0, "reshoot": 0, "need_profile": 0, "queued_profiles": 0, "count": 0}
    with db.session() as s:
        q = select(Product).where(Product.project_id == project_id)
        if product_ids:
            q = q.where(Product.id.in_(product_ids))
        for p in s.scalars(q).all():
            if s.scalar(select(Job.id).where(Job.product_id == p.id, Job.kind == "profile", Job.status.in_(LIVE))):
                continue                      # профиль уже составляется — генерация начнётся после него
            st = context(s, p)[2]
            prof = s.get(ProductProfile, p.current_profile_id).data if p.current_profile_id else None
            manual = st.get("plan_mode") == "manual"
            if not prof or (not manual and _needs_profile(prof, P.plan_of(st))):
                if not s.scalar(select(ProductPhoto.id).where(ProductPhoto.product_id == p.id,
                                                              ProductPhoto.is_reference.is_(True)).limit(1)):
                    continue                  # без фото профиль не составить — товар просто пропускаем
                out["need_profile"] += 1
                if not dry_run and enqueue(s, "profile", project_id, product_id=p.id,
                                           payload={"build": True, "generate": True}, priority=20):
                    out["queued_profiles"] += 1
                continue
            changed, redo = frames_differ(s, p, plan_rows(s, p, prof))
            if not changed:
                continue
            out["products"] += 1
            out["frames"] += changed
            out["reshoot"] += redo
            rebuild_frames(s, p, prof, keep_edited=True)
            if not dry_run:
                log.info("[%s] кадры приведены к пресету перед генерацией: изменено %d, переснимутся %d", p.sku, changed, redo)
        s.flush()
        out["count"] = len(missing_frames(project_id, product_ids, limit, s))
        if dry_run:
            s.rollback()
    if not dry_run and (out["products"] or out["queued_profiles"]):
        say("info", "🎛 Кадры приведены к пресету: " + ", ".join(x for x in [
            f"товаров {out['products']}" if out["products"] else "",
            f"переснимется готовых кадров {out['reshoot']}" if out["reshoot"] else "",
            f"ИИ составит профиль для {out['queued_profiles']}" if out["queued_profiles"] else ""] if x), project_id)
    return out


def _fallback_plan(s, project_id):
    """План товара без своего пресета: пресет проекта или старые настройки плана."""
    from ..core.settings import effective
    project = s.get(Project, project_id)
    pid = int((project.settings or {}).get("preset_id") or 0)
    pr = s.get(GenerationPreset, pid) if pid else None
    if pr and not pr.archived:
        return P.clean_plan(pr.plan)
    return P.plan_of(effective(org_of_project(s, project_id), project))
