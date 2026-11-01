"""Дозагрузка оплаченных результатов Polza.

Номер задачи Polza сохраняется в generations (status=pending) сразу после того, как Polza приняла запрос. Если потом
оборвалась связь, истекло время ожидания, не скачалась картинка или сервер перезапустили — задача не теряется:
раз в минуту фоновый поток опрашивает такие задачи (бесплатный GET) и забирает готовую картинку без повторной оплаты.
"""
import threading
import time
from datetime import timedelta

from sqlalchemy import select

from .. import db
from ..ai import polza
from ..ai.images import fit_side
from ..core import keys, storage
from ..core import presets as presets_core
from ..core.events import say, utcnow
from ..core.logs import Trace, log
from ..db.models import Frame, Generation, Job, Product
from ..services import billing
from ..services.common import context, write_usage
from .queue import ACTIVE, enqueue

EVERY = 60
_lock = threading.Lock()


def candidates():
    """Ждущие генерации, за которыми сейчас никто не следит (задание завершилось или прервано)."""
    with db.session() as s:
        rows = s.execute(select(Generation.id, Generation.job_id, Generation.created_at)
                         .where(Generation.status == "pending").order_by(Generation.id)).all()
        out = []
        for gid, jid, created in rows:
            if jid and s.scalar(select(Job.status).where(Job.id == jid)) in ("queued", "running", "cancelling"):
                continue
            out.append((gid, created))
        return out


def run_once():
    if not _lock.acquire(blocking=False):
        return 0
    try:
        done = 0
        for gid, created in candidates():
            try:
                done += _resume(gid, created)
            except Exception as e:
                log.warning("Дозагрузка генерации %s: %s", gid, str(e)[:200])
        return done
    finally:
        _lock.release()


def _resume(gid, created):
    with db.session() as s:
        g = s.get(Generation, gid)
        frame = s.get(Frame, g.frame_id)
        product = s.get(Product, frame.product_id)
        project, org, st = context(s, product)
        key, task_id, aspect = st.get("api_key"), g.external_id, st.get("aspect")
        others = [k for k in keys.all_secrets(s, org.id) if k != key]
        ids = dict(org=org.id, project=project.id, product=product.id, frame=frame.id)
        sku, pos, model, edit = product.sku, frame.position, g.model, g.instruction
        paid_id = g.paid_operation_id
        job = s.get(Job, g.job_id) if g.job_id else None
        batch_id = job.batch_id if job else None
        billing.by_master.set(bool(job and (job.payload or {}).get("by_master")))
    tag = f"[{sku} #{pos:02d}]"
    if not task_id or (created and utcnow() - created > timedelta(seconds=polza.POLL_GIVE_UP)):
        _mark(gid, "error", "результат Polza не получен за сутки")
        say("err", f"❌ {sku} · кадр {pos:02d}: результат Polza так и не получен — перегенерируйте кадр", ids["project"])
        return 0
    data, last = None, None
    for k in [key] + others:          # если пул ключей менялся — задача могла уйти с другого ключа
        try:
            data = polza.get_task(k, task_id)
            break
        except Exception as e:
            last = e
    if data is None:
        raise last or RuntimeError("задача не найдена")
    status = data.get("status")
    if status not in ("completed", "failed", "cancelled"):
        log.debug("%s дозагрузка: задача %s ещё %s", tag, task_id, status)
        return 0
    if status != "completed":
        from ..services import payments
        paid_cost = polza.cost_of(data)
        if paid_cost:
            payments.settle(paid_id, paid_cost, provider=data.get("provider", ""))
        else:
            payments.release(paid_id, known=True)
        err = data.get("error") or {}
        _mark(gid, "error", str(err.get("message") if isinstance(err, dict) else err)[:1000] or status)
        say("err", f"❌ {sku} · кадр {pos:02d}: задача Polza завершилась с ошибкой — перегенерируйте кадр", ids["project"])
        return 0
    img = polza.extract_image(data)
    if img and aspect:      # модель могла генерировать в другом формате — приводим к формату кадра
        img = polza.crop_to_aspect(img, aspect)
    if img:                 # и к разрешению пресета, если модель вернула меньше
        img = fit_side(img, presets_core.out_side(st), tag, int(st.get("qc_min_side") or 0))
    if not img:
        _mark(gid, "error", "в ответе Polza нет картинки")
        return 0
    cost = polza.cost_of(data)
    from ..services import payments
    payments.settle(paid_id, cost, provider=data.get("provider", ""))
    trace = Trace(tag)
    trace.add("edit" if edit else "generation", model, cost, provider=data.get("provider", ""), paid_operation=paid_id)
    with db.session() as s:
        f = s.get(Frame, ids["frame"], with_for_update=True)
        g = s.get(Generation, gid, with_for_update=True)
        if g is None or g.status != "pending":           # уже забрал кто-то другой
            return 0
        asset = storage.put(s, ids["org"], img, "output", f"{sku}_{pos:02d}_resumed.png")
        g.status, g.output_asset_id, g.cost_rub, g.provider = "ok", asset.id, cost, data.get("provider", "")
        write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"generation:{g.id}")
        f = s.get(Frame, ids["frame"])
        # результат становится текущим, если после него ничего нового не появилось и кадр не принят вручную
        newer = f.current_generation_id is not None and (f.current_generation_id > g.id or f.status == "accepted")
        if not newer and f.status != "retired":
            if f.current_generation_id:
                old = s.get(Generation, f.current_generation_id)
                if old and old.outcome == "current":
                    old.outcome = "archived"
            g.outcome, f.current_generation_id, f.status = "current", g.id, "unchecked"
            became_current = True
            if st.get("qc_enabled"):
                enqueue(s, "check", ids["project"], product_id=ids["product"], frame_id=f.id,
                        batch_id=batch_id, payload={"budget_retry": g.attempt > 1})
        else:
            g.outcome, became_current = "archived", False
    log.info("%s ⤵ дозагружен оплаченный результат задачи %s", tag, task_id)
    say("ok", f"⤵ {sku} · кадр {pos:02d}: результат Polza дозагружен"
        + ("" if became_current else " и добавлен в историю версий кадра"), ids["project"])
    return 1


def _mark(gid, status, error):
    with db.session() as s:
        g = s.get(Generation, gid, with_for_update=True)
        if g and g.status == "pending":
            g.status, g.error = status, error


def _loop():
    time.sleep(20)
    while True:
        try:
            n = run_once()
            if n:
                log.info("Дозагрузка: получено результатов %d", n)
        except Exception as e:
            log.warning("Дозагрузка результатов Polza: %s", e)
        time.sleep(EVERY)


def start():
    threading.Thread(target=_loop, daemon=True, name="polza-resume").start()

