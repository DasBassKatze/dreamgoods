"""Очередь заданий в PostgreSQL.

Задание берётся так: SELECT … FOR UPDATE SKIP LOCKED — несколько воркеров (и несколько процессов/серверов)
не возьмут одно задание дважды. Задания, прерванные перезапуском, автоматически НЕ повторяются:
генерация могла быть уже оплачена.
"""
import os
import socket
import threading
import time
import traceback
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError

from .. import db
from ..core import config
from ..core.events import say, utcnow
from ..core.logs import log
from ..db.models import Frame, Instance, Job, Organization, Product, Project, Client

ACTIVE = ("queued", "running", "cancelling")
HANDLERS = {}          # kind → функция(job_id); заполняет workers/__init__.py

_wake = threading.Event()


def enqueue(s, kind, project_id, product_id=None, frame_id=None, payload=None, priority=100, run_id=None):
    """Ставит задание, если такого же активного ещё нет. Возвращает Job или None."""
    if frame_id is not None:
        s.get(Frame, frame_id, with_for_update=True)
        from ..db.models import Generation
        if kind == "generate" and s.scalar(select(Generation.id).where(Generation.frame_id == frame_id, Generation.status == "pending")):
            return None
        dup = s.scalar(select(Job.id).where(Job.frame_id == frame_id, Job.status.in_(ACTIVE)))
        if dup:
            return None
    elif product_id is not None and kind == "profile":
        dup = s.scalar(select(Job.id).where(Job.product_id == product_id, Job.kind == "profile", Job.status.in_(ACTIVE)))
        if dup:
            return None
    j = Job(kind=kind, project_id=project_id, product_id=product_id, frame_id=frame_id, payload=payload or {},
            priority=priority)
    j.run_id = run_id
    try:
        with s.begin_nested():
            s.add(j)
            s.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) == "23505":
            return None
        raise
    _wake.set()
    return j


def stop(project_id):
    """Снимает задания из очереди; запущенные доделают текущую (уже оплаченную) попытку и остановятся."""
    with db.session() as s:
        n = s.execute(update(Job).where(Job.project_id == project_id, Job.status == "queued")
                      .values(status="cancelled", finished_at=utcnow())).rowcount
        m = s.execute(update(Job).where(Job.project_id == project_id, Job.status == "running")
                      .values(status="cancelling")).rowcount
    say("info", f"Остановка: снято с очереди {n}; в работе {m} — доделают текущую попытку (она оплачена), новых не будет",
        project_id)
    return n


# ───────── копии сервера (instances) и восстановление после сбоя ─────────

INSTANCE_ID = uuid.uuid4().hex[:12]
DEAD_AFTER = timedelta(seconds=60)


def register_instance():
    with db.session() as s:
        s.add(Instance(id=INSTANCE_ID, host=socket.gethostname()[:200], pid=os.getpid()))
    threading.Thread(target=_heartbeat, daemon=True, name="heartbeat").start()


def _heartbeat():
    while True:
        time.sleep(15)
        try:
            with db.session() as s:
                s.execute(update(Instance).where(Instance.id == INSTANCE_ID).values(heartbeat_at=utcnow()))
            recover(quiet=True)
        except Exception as e:
            log.warning("Сердцебиение: %s", e)


def recover(quiet=False):
    """Задания «молчащих» копий (упали или выключены) помечаем ошибкой — без автоповтора: генерация могла быть оплачена.
    Задания живых копий (другой процесс или сервер) не трогаем."""
    with db.session() as s:
        alive = set(s.scalars(select(Instance.id).where(Instance.heartbeat_at >= utcnow() - DEAD_AFTER)).all())
        alive.add(INSTANCE_ID)
        dead = [j for j in s.scalars(select(Job).where(Job.status.in_(("running", "cancelling")))).all()
                if (j.worker or "").split("/")[0] not in alive]
        for j in dead:
            j.status, j.finished_at = "error", utcnow()
            j.error = ("прервано: сервер, выполнявший задание, остановился; повтор не делался, чтобы не заплатить "
                       "дважды. Если Polza успела принять задачу — результат дозагрузится автоматически")
        from ..db.models import BillingOperation
        for j in dead:
            for op in s.scalars(select(BillingOperation).where(BillingOperation.job_id == j.id,
                    BillingOperation.status.in_(("reserved", "submitted")))).all():
                op.status = "released" if op.status == "reserved" else "uncertain"
        s.execute(Instance.__table__.delete().where(Instance.heartbeat_at < utcnow() - timedelta(days=1)))
    if dead:
        log.warning("Прерванных заданий (сервер, который их выполнял, остановился): %d — помечены ошибкой без автоповтора",
                    len(dead))


# ───────── воркеры ─────────

def _claim(worker):
    """Честная очередь для многих пользователей: сначала задания проектов, у которых сейчас меньше всего
    запущенных заданий, — один большой запуск не займёт все потоки и не заставит остальных ждать."""
    other = aliased(Job)
    other_project = aliased(Project)
    busy = (select(func.count(other.id)).join(other_project, other_project.id == other.project_id)
            .where(other_project.client_id == Project.client_id, other.status.in_(("running", "cancelling")))
            .correlate(Project).scalar_subquery())
    with db.session() as s:
        # Serialize admission decisions across server instances; execution remains parallel.
        from sqlalchemy import text
        s.execute(text("SELECT pg_advisory_xact_lock(840621)"))
        j = s.scalars(select(Job).join(Project, Project.id == Job.project_id)
                      .join(Client, Client.id == Project.client_id)
                      .where(Job.status == "queued", busy < func.coalesce(Client.parallel_limit, 2))
                      .order_by(busy, Job.priority, Job.id)
                      .with_for_update(of=Job, skip_locked=True).limit(1)).first()
        if not j:
            return None
        j.status, j.started_at, j.worker = "running", utcnow(), f"{INSTANCE_ID}/{worker}"
        return j.id, j.kind


def _finish(job_id, status, error=""):
    with db.session() as s:
        j = s.get(Job, job_id)
        if j.status == "cancelling" and status == "done":
            status = "cancelled"
        j.status, j.error, j.finished_at, j.note = status, error[:2000], utcnow(), ""


def set_note(job_id, note):
    """Короткая подпись задания для интерфейса: «попытка 2/3», «проверка»…"""
    with db.session() as s:
        s.execute(update(Job).where(Job.id == job_id).values(note=note[:200]))


def cancelled(job_id):
    with db.session() as s:
        return s.scalar(select(Job.status).where(Job.id == job_id)) == "cancelling"


def _where(s, j):
    if j.frame_id:
        f = s.get(Frame, j.frame_id)
        p = s.get(Product, f.product_id) if f else None
        return f"{p.sku if p else '?'} · кадр {f.position:02d}" if f else "кадр"
    if j.product_id:
        p = s.get(Product, j.product_id)
        return p.sku if p else "товар"
    return j.kind


MAX_WORKERS = 12
_par = {"t": 0.0, "n": None}


def parallel():
    """Сколько заданий выполнять одновременно (админ-панель → «Одновременных генераций»). Кэш 10 с."""
    if time.time() - _par["t"] > 10 or _par["n"] is None:
        n = config.WORKERS
        try:
            with db.session() as s:
                v = s.scalar(select(Organization.settings).order_by(Organization.id).limit(1)) or {}
                n = int(v.get("parallel") or config.WORKERS)
        except Exception:
            pass
        _par.update(t=time.time(), n=max(1, min(MAX_WORKERS, n)))
    return _par["n"]


def set_parallel(n):
    n = max(1, min(MAX_WORKERS, int(n)))
    with db.session() as s:
        for org in s.scalars(select(Organization)).all():
            org.settings = {**(org.settings or {}), "parallel": n}
    _par.update(t=time.time(), n=n)
    _wake.set()
    log.info("Очередь: одновременных заданий — %d", n)
    return n


def _funds_ok(job_id):
    """Задание из очереди не запускается, если у клиента закончились деньги (поставлено, пока они были)."""
    from ..services import billing
    with db.session() as s:
        pid = s.scalar(select(Job.project_id).where(Job.id == job_id))
    return not pid or billing.has_funds(pid)


def _worker(name, idx=1):
    while True:
        if idx > parallel():          # «лишние» потоки спят, пока админ не разрешит больше параллельных заданий
            time.sleep(3)
            continue
        try:
            got = _claim(name)
        except Exception as e:
            log.error("Очередь: не удалось взять задание: %s", e)
            time.sleep(5)
            continue
        if not got:
            _wake.wait(2)
            _wake.clear()
            continue
        job_id, kind = got
        try:
            if not _funds_ok(job_id):
                _finish(job_id, "error", "баланс исчерпан — пополните баланс и запустите снова")
                continue
            from ..services.payments import job_context, retry_context
            jt, rt = job_context.set(job_id), retry_context.set(False)
            try:
                HANDLERS[kind](job_id)
            finally:
                job_context.reset(jt)
                retry_context.reset(rt)
            _finish(job_id, "done")
        except Exception as e:
            log.debug("Задание %s: трассировка\n%s", job_id, traceback.format_exc())
            _finish(job_id, "error", str(e))
            with db.session() as s:
                j = s.get(Job, job_id)
                where = _where(s, j)
            say("err", f"❌ {where} · {str(e)[:300]}", j.project_id)


def start_workers(n=None):
    n = n or max(config.WORKERS, MAX_WORKERS)
    for i in range(1, n + 1):
        threading.Thread(target=_worker, args=(f"worker-{i}", i), daemon=True, name=f"worker-{i}").start()
    log.info("Очередь: одновременных заданий %d (можно до %d — меняется в админ-панели)", parallel(), n)

