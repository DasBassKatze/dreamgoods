"""Задание «profile»: ИИ составляет профиль товара по фото (и, если нужно, промпты кадров)."""
from sqlalchemy import select

from .. import db
from ..ai import prompts
from ..core import storage
from ..core.events import say
from ..core.logs import Trace
from ..db.models import Job, Product, ProductProfile
from ..services import billing, moderation
from ..services.common import context, library, rebuild_frames, write_usage
from .queue import set_note
from ..ai.persona import person_hint as person_hint_of
from ..ai.styleref import profile_hint as style_hint_of
from .refs import persona_for, ref_photos, style_for


def handle(job_id):
    with db.session() as s:
        job = s.get(Job, job_id)
        product = s.get(Product, job.product_id)
        project, org, st = context(s, product)
        photos = ref_photos(s, product, 8)
        cats = {k: v.get("name", k) for k, v in library(s, org.id).items()}
        ids = dict(org=org.id, project=project.id, product=product.id)
        sku, labels, build = product.sku, product.label_data or {}, bool((job.payload or {}).get("build"))
        then_generate = build and bool((job.payload or {}).get("generate"))
        assets = [p.asset for p in photos]
        persona, _ = persona_for(s, product, st)
        person_hint = person_hint_of(persona.description, persona.style) if persona else ""
        sref, _ = style_for(s, product, st)
        style_hint = style_hint_of(sref.description, sref.note) if sref else ""
    trace = Trace(f"[{sku}]")
    set_note(job_id, "профиль по фото")
    hint = " | ".join(x for x in ["article: " + ", ".join(labels.get("articles") or []) if labels.get("articles") else "",
                                  "; ".join(labels.get("texts") or [])] if x)
    prof, cost, model = prompts.make_profile(st, sku, [storage.get(a) for a in assets], cats, hint, trace, person_hint, style_hint)
    with db.session() as s:
        product = s.get(Product, ids["product"])
        last = s.scalar(select(ProductProfile.version).where(ProductProfile.product_id == product.id)
                        .order_by(ProductProfile.version.desc()).limit(1)) or 0
        p = ProductProfile(product_id=product.id, version=last + 1, data=prof, source="ai", model=model, cost_rub=cost)
        s.add(p)
        s.flush()
        product.current_profile_id, product.category = p.id, prof["category"]
        if prof.get("summary_ru"):
            product.name = prof["summary_ru"][:300]
        write_usage(s, ids["org"], ids["project"], ids["product"], None, trace, f"profile:{p.id}")
        n = rebuild_frames(s, product, prof) if build else 0
    queued = 0
    if prof.get("prohibited"):           # на фото товара запрещённое содержание — генерацию не запускаем
        moderation.record("photo", "фото товара", "photo", prof["prohibited"], "blocked", ids["project"], ids["product"])
        say("err", f"⛔ {sku}: на фото товара запрещённое содержание ({prof['prohibited'][:140]}) — кадры этого товара "
                   "не снимаются. Загрузите другие фото или исправьте профиль", ids["project"])
        then_generate = False
    if then_generate:        # запуск «Сгенерировать» ждал профиль — ставим недостающие кадры в очередь
        from ..services import frames as frames_svc
        if billing.has_funds(ids["project"]):
            queued = frames_svc.enqueue_frames(ids["project"], frames_svc.missing_frames(ids["project"], [ids["product"]]))
    say("ok", f"🧠 {sku}: профиль готов — {prof['category_ru']}, {prof.get('summary_ru') or prof['object']} · {cost:.2f} ₽"
        + (f" · промптов кадров: {n}" if build else "") + (f" · в очередь кадров: {queued}" if queued else ""), ids["project"])
