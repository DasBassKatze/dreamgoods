"""Состояние проекта для интерфейса: товары, фото, кадры с прогрессом и проверкой, очередь, лента.
Расходы, баланс и метрики — только администратору (admin=True)."""
import re

from sqlalchemy import func, select

from .. import db
from ..ai import polza, prompts
from ..core import presets as presets_core
from ..core.events import STARTED_AT, lines
from ..core.settings import effective, public
from ..db.models import (Frame, Generation, GenerationPreset, ImportFile, ImportSession, Job, Organization, Persona,
                         PersonaPhoto, StyleRef,
                         StyleRefPhoto, Product, ProductPhoto, ProductProfile,
                         Project, QCCheck, UsageEntry)
from . import billing
from . import import_rules as import_rules_mod
from .common import LIVE, persona_id_for
from .metrics import metrics


def _job_state(job):
    """(состояние кадра, подпись, ошибка) по последнему заданию."""
    if not job:
        return "", "", ""
    if job.status == "queued":
        return "queued", "", ""
    if job.status in ("running", "cancelling"):
        return ("checking" if "провер" in (job.note or "") else "running"), job.note or "", ""
    if job.status == "error":
        return "error", "", job.error
    return "", "", ""


_MONEY = re.compile(r"\s*·\s*[\d.,]+\s*₽|\s*·\s*\d+\s*с\s*·\s*[\w\-.—]+$")


def _plain(line):
    """Строка ленты для рядового пользователя: без сумм, секунд и провайдера."""
    return {**line, "text": _MONEY.sub("", line["text"])}


def _market_badge(market, st):
    """Площадка и формат пресета для плашки на карточке товара: «Wildberries · 3:4»."""
    r = presets_core.market_rules(market or {})
    key = r.get("key") or "none"
    return {"market": key, "market_name": "" if key == "none" else r.get("name", ""),
            "aspect": r.get("aspect") or st.get("aspect") or "3:4"}


def state(project_id, admin=False):
    with db.session() as s:
        project = s.get(Project, project_id)
        org = s.get(Organization, project.client.org_id)
        st = effective(org, project)
        products = s.scalars(select(Product).where(Product.project_id == project_id).order_by(func.lower(Product.sku))).all()
        pids = [p.id for p in products]
        photos = s.scalars(select(ProductPhoto).where(ProductPhoto.product_id.in_(pids))
                           .order_by(ProductPhoto.product_id, ProductPhoto.position)).all() if pids else []
        frames = s.scalars(select(Frame).where(Frame.product_id.in_(pids), Frame.status != "retired").order_by(Frame.product_id, Frame.position)).all() if pids else []
        fids = [f.id for f in frames]
        gens = {g.id: g for g in s.scalars(select(Generation).where(Generation.id.in_(
            [f.current_generation_id for f in frames if f.current_generation_id]))).all()} if frames else {}
        qcs = {}                         # последняя проверка по каждой текущей генерации
        if gens:
            for q in s.scalars(select(QCCheck).where(QCCheck.generation_id.in_(list(gens))).order_by(QCCheck.id)).all():
                qcs[q.generation_id] = q
        last_job, prof_job = {}, {}      # последнее активное/ошибочное задание по кадру и по профилю товара
        if pids:
            for j in s.scalars(select(Job).where(Job.project_id == project_id, Job.status.in_(LIVE + ("error",)))
                               .order_by(Job.id)).all():
                if j.frame_id:
                    last_job[j.frame_id] = j
                elif j.product_id and j.kind == "profile":
                    prof_job[j.product_id] = j
        attempts, costs = {}, {}         # попытки и затраты по кадру в задании текущей генерации
        job_ids = {g.job_id for g in gens.values() if g.job_id}
        if job_ids:
            for fid, jid, n, c in s.execute(select(Generation.frame_id, Generation.job_id, func.count(Generation.id),
                                                   func.coalesce(func.sum(Generation.cost_rub), 0))
                                            .where(Generation.job_id.in_(job_ids), Generation.status == "ok")
                                            .group_by(Generation.frame_id, Generation.job_id)).all():
                attempts[(fid, jid)] = n
                costs[(fid, jid)] = float(c)
        waiting = set(s.scalars(select(Generation.frame_id).where(Generation.frame_id.in_(fids),
                                                                  Generation.status == "pending")).all()) if fids else set()
        frame_qc_cost = dict(s.execute(select(QCCheck.frame_id, func.sum(QCCheck.cost_rub)).where(QCCheck.frame_id.in_(fids))
                                       .group_by(QCCheck.frame_id)).all()) if fids else {}
        profiles = {pp.id: pp for pp in s.scalars(select(ProductProfile).where(ProductProfile.id.in_(
            [p.current_profile_id for p in products if p.current_profile_id]))).all()} if products else {}

        by_photos, by_frames = {}, {}
        for ph in photos:
            by_photos.setdefault(ph.product_id, []).append(ph)
        for f in frames:
            by_frames.setdefault(f.product_id, []).append(f)

        # какая модель клиента снимает каждый товар (своя → по группе → проекта)
        client_personas = {x.id: x for x in s.scalars(select(Persona).where(Persona.client_id == project.client_id,
                                                                            Persona.status == "ready")).all()}
        rules = [(x.id, x.groups or []) for x in client_personas.values()]

        def persona_view(prod):
            pid, via = persona_id_for(s, prod, st, rules)
            x = client_personas.get(pid)
            return {"id": x.id, "name": x.name, "via": via} if x else None

        out, done_all, total_all, review_n = [], 0, 0, 0
        for p in products:
            fr_out, done = [], 0
            for f in by_frames.get(p.id, []):
                g = gens.get(f.current_generation_id)
                ui, note, err = _job_state(last_job.get(f.id))
                if f.id in waiting and ui in ("", "error"):
                    ui, note, err = "running", "ждём результат Polza", ""
                if g:
                    done += 1
                block, shot = prompts.frame_label(f.prompt)
                block = f.title or block
                qv = None
                if g or f.status == "rejected":
                    q = qcs.get(f.current_generation_id)
                    key = (f.id, g.job_id) if g else None
                    qv = {"status": f.status, "defects": list(q.reasons) if q else [], "counts": q.counts if q else None,
                          "attempts": attempts.get(key, 1) if g else 0,
                          "cost": round(costs.get(key, g.cost_rub if g else 0) + float(frame_qc_cost.get(f.id) or 0), 2),
                          "model": q.model if q else None}
                    if not admin:
                        qv["cost"], qv["model"] = None, None
                    if f.status == "review" and g:
                        review_n += 1
                fr_out.append({"id": f.id, "i": f.position, "block": block, "shot": shot,
                               "state": ui or ("done" if g else "missing"), "note": note, "error": err,
                               "generation": g.id if g else None,
                               "asset": str(g.output_asset_id) if g and g.output_asset_id else None, "qc": qv})
            done_all += done
            total_all += len(fr_out)
            pp = profiles.get(p.current_profile_id)
            pj = prof_job.get(p.id)
            out.append({
                "id": p.id, "sku": p.sku, "name": p.name, "persona_id": p.persona_id, "preset_id": p.preset_id,
                "persona": persona_view(p),
                "style_ref_id": p.style_ref_id,
                "photos": [{"asset": str(ph.asset_id), "selected": ph.is_reference, "role": ph.role, "view": ph.view}
                           for ph in by_photos.get(p.id, []) if ph.role != "label"],
                "frames": fr_out, "done": done, "total": len(fr_out),
                "profile": {"category": pp.data.get("category_ru"), "subcategory": pp.data.get("subcategory_ru") or "", "summary": pp.data.get("summary_ru") or pp.data.get("object"),
                            "version": pp.version} if pp else None,
                "profile_job": {"state": "running"} if pj and pj.status in LIVE else
                               {"state": "error", "error": pj.error} if pj and pj.status == "error" else None})

        warnings = []
        new = [m["sku"] for m in out if not m["total"]]
        if new:
            warnings.append(f"Без промптов: {len(new)} товаров ({', '.join(new[:5])}{'…' if len(new) > 5 else ''}) — "
                            "нажмите «✨ Промпты для новых», чтобы ИИ составил профиль товара и промпты по фото")

        count = lambda *w: s.scalar(select(func.count(Job.id)).where(Job.project_id == project_id, *w))
        queued = count(Job.status == "queued")
        running = count(Job.status.in_(("running", "cancelling")))
        stopping = bool(count(Job.status == "cancelling"))
        ok = count(Job.status == "done", Job.finished_at >= STARTED_AT)
        fail = count(Job.status == "error", Job.finished_at >= STARTED_AT)
        errors = count(Job.status == "error", Job.frame_id.is_not(None))
        spent = s.scalar(select(func.coalesce(func.sum(UsageEntry.amount_rub), 0)).where(
            UsageEntry.project_id == project_id, UsageEntry.created_at >= STARTED_AT))
        spent_all = float(s.scalar(select(func.coalesce(func.sum(UsageEntry.amount_rub), 0))
                                   .where(UsageEntry.project_id == project_id)) or 0)
        recent = s.scalars(select(UsageEntry.amount_rub).where(UsageEntry.project_id == project_id,
                                                               UsageEntry.kind == "generation", UsageEntry.amount_rub > 0)
                           .order_by(UsageEntry.id.desc()).limit(20)).all()
        met = metrics(s, project_id, spent_all) if admin else None
        proj = {"id": project.id, "name": project.name, "client": project.client.name}
        preset_names = {x.id: {"id": x.id, "name": x.name, "total": presets_core.preset_total(x), "quality": x.quality,
                                     "plan_mode": x.plan_mode or "auto",
                                     **_market_badge(x.market, st)}
                        for x in s.scalars(select(GenerationPreset).where(GenerationPreset.org_id == org.id,
                                                                          GenerationPreset.archived.is_(False),
                                                                          GenerationPreset.client_id.is_(None)
                                                                          | (GenerationPreset.client_id == project.client_id))).all()}
        preset = preset_names.get(int(st.get("preset_id") or 0))
        style_ref = None                 # референс оформления проекта
        sid = int(st.get("style_ref_id") or 0)
        sr = s.get(StyleRef, sid) if sid else None
        if sr and sr.status == "ready":
            ph = s.scalars(select(StyleRefPhoto.asset_id).where(StyleRefPhoto.style_ref_id == sr.id)
                           .order_by(StyleRefPhoto.position)).first()
            style_ref = {"id": sr.id, "name": sr.name, "asset": str(ph) if ph else None}
        persona = None                   # модель клиента по умолчанию в проекте
        pid_default = int(st.get("persona_id") or 0)
        pp_ = s.get(Persona, pid_default) if pid_default else None
        if pp_ and pp_.status == "ready":
            main = s.scalars(select(PersonaPhoto.asset_id).where(PersonaPhoto.persona_id == pp_.id,
                                                                 PersonaPhoto.kind.in_(("main", "photo")))
                             .order_by(PersonaPhoto.kind, PersonaPhoto.position)).first()
            persona = {"id": pp_.id, "name": pp_.name, "asset": str(main) if main else None}
        options = {
            "personas": [{"id": x.id, "name": x.name} for x in s.scalars(select(Persona).where(
                Persona.client_id == project.client_id, Persona.status == "ready").order_by(Persona.id)).all()],
            "styles": [{"id": x.id, "name": x.name} for x in s.scalars(select(StyleRef).where(
                StyleRef.client_id == project.client_id, StyleRef.status == "ready").order_by(StyleRef.id)).all()],
        }
        open_import = None               # незавершённая загрузка фото — к ней можно вернуться
        row = s.execute(select(ImportSession.id, ImportSession.status, func.count(ImportFile.id))
                        .join(ImportFile, ImportFile.session_id == ImportSession.id)
                        .where(ImportSession.project_id == project_id,
                               ImportSession.status.in_(("upload", "analyzing", "ready", "error")))
                        .group_by(ImportSession.id).order_by(ImportSession.id.desc()).limit(1)).first()
        if row:
            open_import = {"id": row[0], "status": row[1], "count": row[2]}
        import_rules = import_rules_mod.clean((project.settings or {}).get("import_rules"))
        settings = public(org, project)
        client = project.client
        markup = billing.markup_of(client, org)
        account = {"balance": round(client.balance_rub or 0, 2), "billing": client.billing, "client": client.name}
    b = polza.balance(st.get("api_key")) if admin else {"value": None, "error": ""}
    log_lines = lines(project_id) if admin else [_plain(x) for x in lines(project_id, include_global=False)]
    spent_v = round(float(spent or 0), 2) if admin else None
    return {"admin": admin, "project": proj, "persona": persona, "style_ref": style_ref, "preset": preset, "presets": list(preset_names.values()), "options": options, "settings": settings, "warnings": warnings, "products": out,
            "runner": {"queued": queued, "running": running, "busy": bool(queued or running), "ok": ok, "fail": fail,
                       "errors": errors, "spent": spent_v, "stopping": stopping},
            "log": log_lines,
            "totals": {"done": done_all, "total": total_all, "review": review_n, "spent_all": round(spent_all, 2) if admin else None,
                       "avg_cost": round(sum(recent) / len(recent) * (1 if admin else markup), 2) if recent else 0.0},
            "account": account, "open_import": open_import, "import_rules": import_rules,
            "metrics": met, "balance": b["value"], "balance_error": b["error"]}
