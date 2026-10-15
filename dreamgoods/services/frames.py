"""Действия с кадрами: генерация, проверка, промпты, ручное решение."""
from sqlalchemy import func, select, update

from .. import db
from ..ai import prompts
from ..core.events import say
from ..core.logs import log
from ..db.models import Frame, Generation, Job, Product, QCCheck, Review
from ..workers.queue import enqueue
from .common import LIVE, frame_in


def missing_frames(project_id, product_ids=None, limit=0, s=None):
    """Кадры без картинки, которые сейчас не в работе."""
    if s is None:
        with db.session() as s2:
            return missing_frames(project_id, product_ids, limit, s2)
    q = (select(Frame.id).join(Product, Product.id == Frame.product_id)
         .where(Product.project_id == project_id, Frame.current_generation_id.is_(None), Frame.status.not_in(("accepted", "retired")))
         .order_by(func.lower(Product.sku), Frame.position))
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    ids = s.scalars(q).all()
    busy = set(s.scalars(select(Job.frame_id).where(Job.frame_id.in_(ids), Job.status.in_(LIVE))).all()) if ids else set()
    ids = [i for i in ids if i not in busy]
    return ids[:limit] if limit else ids


def checkable_frames(project_id, product_ids=None, frame_ids=None, only_unchecked=True):
    """Готовые кадры для проверки: конкретные (frame_ids) или все/непроверенные в выбранных товарах."""
    with db.session() as s:
        q = (select(Frame.id).join(Product, Product.id == Frame.product_id)
             .where(Product.project_id == project_id, Frame.current_generation_id.is_not(None)))
        if product_ids:
            q = q.where(Product.id.in_(product_ids))
        if frame_ids is not None:
            q = q.where(Frame.id.in_(frame_ids))
        elif only_unchecked:
            q = q.where(Frame.status == "unchecked")
        return s.scalars(q.order_by(func.lower(Product.sku), Frame.position)).all()


def frames_of_project(project_id, frame_ids):
    """Фильтрует id кадров: только кадры этого проекта."""
    if not frame_ids:
        return []
    with db.session() as s:
        return s.scalars(select(Frame.id).join(Product, Product.id == Frame.product_id)
                         .where(Product.project_id == project_id, Frame.id.in_(frame_ids), Frame.status != "retired")).all()


def enqueue_frames(project_id, frame_ids, kind="generate", payload=None):
    """Опорные кадры серии (первый кадр группы товара: обложка, первый кадр на модели) — в очередь первыми:
    остальные кадры товара снимаются по ним."""
    from ..ai import series
    n = 0
    with db.session() as s:
        first = {}
        if kind == "generate" and frame_ids:
            for f in s.scalars(select(Frame).where(Frame.id.in_(frame_ids))).all():
                if f.product_id not in first:
                    mates = s.scalars(select(Frame).where(Frame.product_id == f.product_id, Frame.status != "retired")
                                      .order_by(Frame.position)).all()
                    seen = {}
                    for m in mates:
                        seen.setdefault(series.group_of(m.prompt), m.id)
                    first[f.product_id] = set(seen.values())
        for fid in frame_ids:
            f = s.get(Frame, fid)
            prio = 90 if fid in first.get(f.product_id, ()) else 100
            if enqueue(s, kind, project_id, product_id=f.product_id, frame_id=fid, payload=payload, priority=prio):
                n += 1
    return n


def clear_errors(project_id):
    with db.session() as s:
        s.execute(update(Job).where(Job.project_id == project_id, Job.status == "error").values(status="dismissed"))


def get_prompt(project_id, frame_id):
    with db.session() as s:
        _, f = frame_in(s, project_id, frame_id)
        return f.prompt


def set_prompt(project_id, frame_id, text):
    with db.session() as s:
        p, f = frame_in(s, project_id, frame_id)
        f.prompt, f.prompt_source, f.prompt_edited = text.strip(), "manual", True
        f.block = prompts.block_of(f.prompt)
        sku, pos = p.sku, f.position
    log.info("[%s #%02d] промпт изменён вручную", sku, pos)


def review(project_id, frame_id, verdict, comment, regen):
    """Ручное решение по кадру. Брак: генерация уходит в отклонённые; regen — перегенерация с замечанием."""
    with db.session() as s:
        p, f = frame_in(s, project_id, frame_id)
        if s.scalar(select(Job.id).where(Job.frame_id == f.id, Job.status.in_(LIVE))):
            raise ValueError("кадр сейчас в работе")
        if not f.current_generation_id:
            raise ValueError("кадр ещё не сгенерирован")
        g = s.get(Generation, f.current_generation_id)
        q = s.scalars(select(QCCheck).where(QCCheck.generation_id == g.id).order_by(QCCheck.id.desc()).limit(1)).first()
        ai = ("pass" if q.passed else "fail") if q else ""
        kind = ""
        if comment:
            kind = "false_alarm" if ai == "fail" and verdict == "ok" else "missed" if ai == "pass" and verdict == "bad" else "note"
        s.add(Review(frame_id=f.id, generation_id=g.id, verdict=verdict, ai_verdict=ai, comment=comment, note_kind=kind))
        if verdict == "ok":
            f.status = "accepted"
        else:
            g.outcome = "rejected"
            f.current_generation_id, f.status = None, "rejected"
            if regen:
                enqueue(s, "generate", project_id, product_id=p.id, frame_id=f.id, payload={"comment": comment})
        sku, pos = p.sku, f.position
    agree = "" if not ai else (" · совпало с ИИ" if (ai == "pass") == (verdict == "ok") else
                               " · ИИ ОШИБСЯ (" + ("пропустил брак" if ai == "pass" else "зря отбраковал") + ")")
    log.info("[%s #%02d] ручное решение: %s%s%s", sku, pos, "ПРИНЯТ" if verdict == "ok" else "БРАК",
             f" «{comment}»" if comment else "", agree)
    if regen and verdict == "bad":
        say("info", f"↻ {sku} · кадр {pos:02d}: брак отклонён вручную, перегенерация"
            + (f" с замечанием «{comment[:80]}»" if comment else ""), project_id)


# ───────── правка готового фото по промпту и версии кадра ─────────

QUICK = {
    "upscale": ("Upscale this exact photo to maximum quality: identical composition, product, person, colors and lighting; "
                "only add fine detail and sharpness, remove noise and artifacts. Do not change anything else.",
                "улучшить до 4K", {"resolution": "4K"}),
    "remove_bg": ("Remove the background: place the product on a pure white seamless background (#FFFFFF) with a soft natural "
                  "shadow under it. Remove people, props and the scene; keep the product exactly the same — shape, color, "
                  "materials, every detail — at the same angle, centered and filling about 80% of the frame.",
                  "убрать фон", {}),
}


def quick(project_id, frame_id, action):
    """Быстрые действия с готовым кадром (кнопки на карточке и в панели «Детали изображения»)."""
    text, label, extra = QUICK[action]
    edit(project_id, frame_id, text, label=label, extra=extra)


def edit(project_id, frame_id, instruction, source_id=None, label="", extra=None):
    """Ставит правку: текущая (или выбранная) версия кадра + фото товара → генератор с просьбой изменить только
    указанное. Результат проходит ИИ-проверку и становится текущей версией; прежняя остаётся в истории."""
    instruction = (instruction or "").strip()
    if len(instruction) < 3:
        raise ValueError("опишите, что изменить на фото")
    with db.session() as s:
        p, f = frame_in(s, project_id, frame_id)
        if s.scalar(select(Job.id).where(Job.frame_id == f.id, Job.status.in_(LIVE))):
            raise ValueError("кадр сейчас в работе — дождитесь окончания")
        src = int(source_id or f.current_generation_id or 0)
        g = s.get(Generation, src) if src else None
        if not g or g.frame_id != f.id or not g.output_asset_id:
            raise ValueError("править нечего: кадр ещё не сгенерирован")
        enqueue(s, "generate", project_id, product_id=p.id, frame_id=f.id,
                payload={"edit": instruction[:1500], "source": src, "label": label, **(extra or {})}, priority=50)
        sku, pos = p.sku, f.position
    say("info", f"✏ {sku} · кадр {pos:02d}: {label or 'правка «' + instruction[:80] + '»'}", project_id)


def history(project_id, frame_id, admin=False):
    """Все готовые версии кадра (новые сверху): генерации и правки, текущая отмечена."""
    with db.session() as s:
        _, f = frame_in(s, project_id, frame_id)
        gens = s.scalars(select(Generation).where(Generation.frame_id == f.id, Generation.status.in_(("ok", "pending")))
                         .order_by(Generation.id.desc()).limit(60)).all()
        qcs = {}
        for q in s.scalars(select(QCCheck).where(QCCheck.generation_id.in_([g.id for g in gens])).order_by(QCCheck.id)).all():
            qcs[q.generation_id] = q
        out = []
        for g in gens:
            q = qcs.get(g.id)
            item = {"id": g.id, "asset": str(g.output_asset_id) if g.output_asset_id else None,
                    "current": g.id == f.current_generation_id, "pending": g.status == "pending",
                    "outcome": g.outcome or "", "edit": g.instruction or "", "source": g.source_id,
                    "created": g.created_at.isoformat() if g.created_at else None,
                    "qc": None if not q else ("pass" if q.passed else "fail")}
            if admin:
                item.update(model=g.model, provider=g.provider, cost=round(g.cost_rub or 0, 2), seconds=round(g.seconds or 0))
            out.append(item)
        return out


def restore(project_id, frame_id, generation_id):
    """Делает выбранную версию текущей (прежняя текущая уходит в историю)."""
    with db.session() as s:
        p, f = frame_in(s, project_id, frame_id)
        if s.scalar(select(Job.id).where(Job.frame_id == f.id, Job.status.in_(LIVE))):
            raise ValueError("кадр сейчас в работе — дождитесь окончания")
        g = s.get(Generation, int(generation_id))
        if not g or g.frame_id != f.id or g.status != "ok" or not g.output_asset_id:
            raise LookupError("версия не найдена")
        if f.current_generation_id == g.id:
            return
        if f.current_generation_id:
            old = s.get(Generation, f.current_generation_id)
            if old and old.outcome == "current":
                old.outcome = "archived"
        q = s.scalars(select(QCCheck).where(QCCheck.generation_id == g.id).order_by(QCCheck.id.desc()).limit(1)).first()
        g.outcome, f.current_generation_id = "current", g.id
        f.status = "unchecked" if q is None else ("pass" if q.passed else "review")
        sku, pos = p.sku, f.position
    log.info("[%s #%02d] возвращена версия #%s", sku, pos, generation_id)


def project_history(project_id, admin=False, limit=120, before=None):
    """Лента генераций проекта (новые сверху): кадр, товар, картинка, правка или съёмка, итог проверки."""
    with db.session() as s:
        q = (select(Generation, Frame, Product).join(Frame, Frame.id == Generation.frame_id)
             .join(Product, Product.id == Frame.product_id)
             .where(Product.project_id == project_id, Generation.status.in_(("ok", "pending", "error"))))
        if before:
            q = q.where(Generation.id < int(before))
        rows = s.execute(q.order_by(Generation.id.desc()).limit(limit)).all()
        gids = [g.id for g, _, _ in rows]
        qcs = {}
        for c in s.scalars(select(QCCheck).where(QCCheck.generation_id.in_(gids)).order_by(QCCheck.id)).all() if gids else []:
            qcs[c.generation_id] = c
        out = []
        for g, f, p in rows:
            c = qcs.get(g.id)
            item = {"id": g.id, "frame_id": f.id, "product_id": p.id, "sku": p.sku, "position": f.position,
                    "title": f.title or prompts.frame_label(f.prompt)[0], "asset": str(g.output_asset_id) if g.output_asset_id else None,
                    "status": g.status, "current": g.id == f.current_generation_id, "edit": g.instruction or "",
                    "attempt": g.attempt, "created": g.created_at.isoformat() if g.created_at else None,
                    "qc": None if not c else ("pass" if c.passed else "fail"),
                    "error": (g.error or "")[:200] if g.status == "error" else ""}
            if admin:
                item.update(model=g.model, cost=round(g.cost_rub or 0, 2))
            out.append(item)
        return out
