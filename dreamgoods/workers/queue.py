"""Очередь заданий в PostgreSQL.

Задание берётся так: SELECT … FOR UPDATE SKIP LOCKED — несколько воркеров (и несколько процессов/серверов)
не возьмут одно задание дважды. Задания, прерванные перезапуском, автоматически НЕ повторяются:
генерация могла быть уже оплачена.
"""
import os
import random
import socket
import threading
import time
import traceback
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update, text
from sqlalchemy.orm import aliased

from .. import db
from ..core import config
from ..core.events import say, utcnow
from ..core.logs import log
from ..db.models import Frame, Generation, Instance, Job, Organization, Product

ACTIVE = ("queued", "running", "cancelling", "paused")
HANDLERS = {}          # kind → функция(job_id); заполняет workers/__init__.py

_wake = threading.Event()
_shutdown = threading.Event()
_worker_threads = []


def enqueue(s, kind, project_id, product_id=None, frame_id=None, payload=None, priority=100, batch_id=None):
    """Ставит задание, если такого же активного ещё нет. Возвращает Job или None."""
    if frame_id is not None:
        frame = s.get(Frame, frame_id, with_for_update=True)
        product = s.get(Product, frame.product_id) if frame else None
        if not product or product.project_id != project_id:
            raise LookupError("кадр не найден в проекте")
        if kind == "generate" and s.scalar(select(Generation.id).where(
                Generation.frame_id == frame_id, Generation.status == "pending").limit(1)):
            return None
        dup = s.scalar(select(Job.id).where(Job.frame_id == frame_id, Job.status.in_(ACTIVE)))
        if dup:
            return None
    elif product_id is not None and kind == "profile":
        product = s.get(Product, product_id, with_for_update=True)
        if not product or product.project_id != project_id:
            raise LookupError("товар не найден в проекте")
        dup = s.scalar(select(Job.id).where(Job.product_id == product_id, Job.kind == "profile", Job.status.in_(ACTIVE)))
        if dup:
            return None
    from ..services.billing import by_master
    from ..services.payments import batch_context
    if batch_id is None: batch_id = batch_context.get()
    payload = dict(payload or {})
    if by_master.get():
        payload["by_master"] = True          # запустил мастер — оплата напрямую с Polza
    j = Job(batch_id=batch_id, kind=kind, project_id=project_id, product_id=product_id, frame_id=frame_id, payload=payload,
            priority=priority)
    s.add(j)
    s.flush()
    _wake.set()
    return j


def stop(project_id):
    """Снимает задания из очереди; запущенные доделают текущую (уже оплаченную) попытку и остановятся."""
    with db.session() as s:
        n = s.execute(update(Job).where(Job.project_id == project_id, Job.status.in_(("queued", "paused")))
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


def _trim_memory():
    """Linux: вернуть системе память, освобождённую после обработки картинок (glibc держит её у себя).
    При сотнях потоков без этого процесс «раздувается» до гигабайт. На Windows не нужно."""
    try:
        import ctypes
        import sys
        if sys.platform.startswith("linux"):
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _heartbeat():
    while True:
        time.sleep(15)
        _trim_memory()
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
            if j.kind == "import":          # анализ загрузки: сессия снова доступна — его можно запустить ещё раз
                from ..db.models import ImportSession
                from ..services.importer import STALE_ERROR
                sess = s.get(ImportSession, int((j.payload or {}).get("session") or 0))
                if sess is not None and sess.status == "analyzing":
                    sess.status, sess.error = "error", STALE_ERROR
            from ..db.models import PaidOperation
            for operation in s.scalars(select(PaidOperation).where(PaidOperation.job_id == j.id,
                    PaidOperation.status.in_(("reserved", "submitted")))).all():
                operation.status = "released" if operation.status == "reserved" else "uncertain"
                if operation.status == "uncertain" and operation.batch_id:
                    from ..db.models import BudgetBatch
                    batch = s.get(BudgetBatch, operation.batch_id)
                    batch.state, batch.pause_reason = "paused", "Сервер прервался после отправки запроса. Требуется сверка резерва."
            j.status, j.finished_at = "error", utcnow()
            j.error = ("прервано: сервер, выполнявший задание, остановился; повтор не делался, чтобы не заплатить "
                       "дважды. Если Polza успела принять задачу — результат дозагрузится автоматически")
        s.execute(Instance.__table__.delete().where(Instance.heartbeat_at < utcnow() - timedelta(days=1)))
    if dead:
        log.warning("Прерванных заданий (сервер, который их выполнял, остановился): %d — помечены ошибкой без автоповтора",
                    len(dead))


# ───────── воркеры ─────────

def _claim(worker):
    """Честная очередь для многих пользователей: сначала задания проектов, у которых сейчас меньше всего
    запущенных заданий, — один большой запуск не займёт все потоки и не заставит остальных ждать."""
    from ..db.models import Project, BudgetBatch
    other = aliased(Job)
    other_project = aliased(Project)
    busy = (select(func.count(other.id)).join(other_project, other_project.id == other.project_id)
            .where(other_project.client_id == Project.client_id, other.status.in_(("running", "cancelling")))
            .correlate(Project).scalar_subquery())
    with db.session() as s:
        # Все процессы считают тарифные лимиты и переводят задание в running последовательно.
        if s.bind.dialect.name == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7430019)"))
        offset = 0
        while True:
            if _shutdown.is_set():
                return None
            cands = s.scalars(select(Job).outerjoin(Project, Project.id == Job.project_id)
                              .where(Job.status == "queued", ~select(BudgetBatch.id).where(
                                  BudgetBatch.id == Job.batch_id, BudgetBatch.state == "paused").exists()).order_by(Job.priority, busy, Job.id)
                              .with_for_update(of=Job, skip_locked=True).offset(offset).limit(30)).all()
            if not cands:
                return None
            j = _within_plan(s, cands)
            if j:
                j.status, j.started_at, j.worker = "running", utcnow(), f"{INSTANCE_ID}/{worker}"
                return j.id, j.kind
            offset += len(cands)


def _within_plan(s, cands):
    """Первое задание, у клиента которого не превышен лимит одновременных заданий по тарифу."""
    if not cands:
        return None
    from ..db.models import Project
    from ..services.plans import parallel_for
    pids = {j.project_id for j in cands if j.project_id}
    client_of = dict(s.execute(select(Project.id, Project.client_id).where(Project.id.in_(pids))).all()) if pids else {}
    running = dict(s.execute(select(Project.client_id, func.count(Job.id)).join(Project, Project.id == Job.project_id)
                             .where(Job.status.in_(("running", "cancelling")),
                                    Project.client_id.in_(set(client_of.values()) or {0}))
                             .group_by(Project.client_id)).all()) if client_of else {}
    limit = {}
    for j in cands:
        cid = client_of.get(j.project_id)
        if cid is None:
            return j
        if cid not in limit:
            limit[cid] = parallel_for(s, cid)
        if limit[cid] is None or running.get(cid, 0) < limit[cid]:
            return j
    return None


def _finish(job_id, status, error=""):
    with db.session() as s:
        j = s.get(Job, job_id)
        if j.status == "cancelling" and status == "done":
            status = "cancelled"
        j.status, j.error, j.finished_at, j.note = status, error[:2000], utcnow(), ""
        if status == "done" and (j.payload or {}).get("deferred_budget_check") and j.frame_id:
            payload=dict(j.payload)
            payload.pop("deferred_budget_check",None)
            j.payload=payload
            s.flush()
            f=s.get(Frame,j.frame_id,with_for_update=True)
            if f and f.current_generation_id and f.status not in ("accepted","retired"):
                enqueue(s,"check",j.project_id,product_id=j.product_id,frame_id=j.frame_id,batch_id=j.batch_id,
                        payload={"by_master":bool(payload.get("by_master")),"budget_retry":bool(payload.get("deferred_retry"))})


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


MAX_WORKERS = 200          # потоки дешёвые: ожидание Polza — сон на событии, опрос статусов общий (ai/throttle.py)
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
    """Задание из очереди не запускается, если у клиента закончились деньги (поставлено, пока они были).
    Заодно выставляет «запустил мастер» для обработчика задания."""
    from ..services import billing
    with db.session() as s:
        pid, payload = s.execute(select(Job.project_id, Job.payload).where(Job.id == job_id)).one()
    billing.by_master.set(bool((payload or {}).get("by_master")))
    return True  # доступные средства проверяются атомарно перед каждым платным запросом


def _run_handler(job_id, kind):
    """Сохраняем известные расходы даже при ошибке разбора ответа/скачивания/профиля."""
    from ..core.logs import pending_traces
    from ..db.models import Client, Project
    from ..services.common import write_usage
    from ..services import payments
    with db.session() as s:
        job = s.get(Job, job_id)
        batch_id = job.batch_id
        retry = bool((job.payload or {}).get("budget_retry"))
    job_token = payments.job_context.set(job_id)
    batch_token = payments.batch_context.set(batch_id)
    retry_token = payments.retry_context.set(retry)
    traces = []
    token = pending_traces.set(traces)
    try:
        HANDLERS[kind](job_id)
    finally:
        try:
            if any(t.usage for t in traces):
                with db.session() as s:
                    j = s.get(Job, job_id)
                    p = s.get(Project, j.project_id) if j and j.project_id else None
                    c = s.get(Client, p.client_id) if p else None
                    if c:
                        for trace in traces:
                            write_usage(s, c.org_id, p.id, j.product_id, j.frame_id, trace, f"job:{job_id}")
        finally:
            pending_traces.reset(token)
            payments.retry_context.reset(retry_token)
            payments.batch_context.reset(batch_token)
            payments.job_context.reset(job_token)


def _worker(name, idx=1):
    while not _shutdown.is_set():
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
            _wake.wait(3 + random.uniform(0, 2))     # разброс — сотни простаивающих потоков не опрашивают базу строем
            _wake.clear()
            continue
        job_id, kind = got
        try:
            if not _funds_ok(job_id):
                _finish(job_id, "error", "баланс исчерпан — пополните баланс и запустите снова")
                continue
            _run_handler(job_id, kind)
            _finish(job_id, "done")
        except Exception as e:
            log.debug("Задание %s: трассировка\n%s", job_id, traceback.format_exc())
            from ..services.payments import BudgetPause
            _finish(job_id, "paused" if isinstance(e, BudgetPause) else "error", str(e))
            with db.session() as s:
                j = s.get(Job, job_id)
                where = _where(s, j)
            say("err", f"❌ {where} · {str(e)[:300]}", j.project_id)


def start_workers(n=None):
    n = n or MAX_WORKERS
    for i in range(1, n + 1):
        thread = threading.Thread(target=_worker, args=(f"worker-{i}", i), daemon=True, name=f"worker-{i}")
        _worker_threads.append(thread)
        thread.start()
    log.info("Очередь: одновременных заданий %d (можно до %d — меняется в админ-панели)", parallel(), n)



def shutdown_workers():
    """Desktop: stop claiming jobs and finish already paid work before stopping PostgreSQL."""
    _shutdown.set()
    _wake.set()
    for thread in _worker_threads:
        thread.join()
