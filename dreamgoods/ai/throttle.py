"""Массовая параллельная работа с API Polza.

Как устроено (рассчитано на сотни одновременных генераций):

1. Отправка задач (POST /media) идёт через адаптивный ограничитель скорости на каждый ключ — «ведро с жетонами»
   + AIMD, как в TCP: пока Polza отвечает нормально, скорость плавно растёт (+0.25 запр/с за успех), при «занято»
   (429/502/503/504) — резко падает (×0.6) и все потоки этого ключа ждут Retry-After. Так сервис сам находит
   предельную скорость ключа и не упирается в лимиты пачкой отказов.
2. Ожидание результата не занимает отдельный поток на опрос: задачи регистрируются в общем опросчике, который
   проверяет статусы пакетно, своим небольшим пулом и со своим ограничителем. Поток задания просто спит на событии.
   Поэтому 100–200 одновременных генераций — это 100–200 спящих потоков и ~20–40 лёгких GET в секунду, а не шквал.
3. Тяжёлые операции (загрузка фото в хранилище Polza, скачивание результата, запросы к модели проверки)
   ограничены семафорами, чтобы не забить канал и память.
"""
import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from ..core.logs import log


class AdaptiveLimiter:
    """Жетоны с адаптивной скоростью (AIMD). acquire() блокирует, пока нельзя отправлять."""

    def __init__(self, name, rate=3.0, burst=6, min_rate=0.3, max_rate=25.0):
        self.name, self.rate, self.burst = name, rate, burst
        self.min_rate, self.max_rate = min_rate, max_rate
        self.tokens, self.t = float(burst), time.monotonic()
        self.blocked_until = 0.0
        self.lock = threading.Lock()
        self.ok = self.throttled = self.sent = 0
        self.events = deque(maxlen=200)          # (время, «занято») — для статистики за час

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
                self.t = now
                wait = max(0.0, self.blocked_until - now)
                if not wait and self.tokens >= 1:
                    self.tokens -= 1
                    self.sent += 1
                    return
                if not wait:
                    wait = (1 - self.tokens) / self.rate
            time.sleep(min(wait, 5) + random.uniform(0, 0.05))   # небольшой разброс — потоки не просыпаются строем

    def on_ok(self):
        with self.lock:
            self.ok += 1
            self.rate = min(self.max_rate, self.rate + 0.25)
            self.burst = max(4, min(30, round(self.rate * 2)))

    def on_throttle(self, retry_after=None):
        with self.lock:
            self.throttled += 1
            self.events.append(time.time())
            self.rate = max(self.min_rate, self.rate * 0.6)
            pause = float(retry_after) if retry_after else 3.0
            self.blocked_until = max(self.blocked_until, time.monotonic() + min(max(pause, 1.0), 120.0))
            self.tokens = 0.0
        log.warning("Polza (%s): «занято» — снижаю скорость до %.1f запр/с, пауза %.0f с", self.name, self.rate, pause)

    def stats(self):
        hour = time.time() - 3600
        return {"rate": round(self.rate, 2), "sent": self.sent, "ok": self.ok,
                "throttled_hour": sum(1 for t in self.events if t >= hour)}


_limiters, _lim_lock = {}, threading.Lock()


def limiter(kind, key=""):
    """kind: submit — создание задач; poll — опрос статусов; chat — модель проверки; upload — хранилище."""
    defaults = {"submit": dict(rate=3.0, max_rate=25.0), "poll": dict(rate=20.0, burst=40, max_rate=60.0),
                "chat": dict(rate=6.0, max_rate=40.0), "upload": dict(rate=6.0, max_rate=30.0)}
    k = (kind, (key or "")[-12:])
    with _lim_lock:
        if k not in _limiters:
            _limiters[k] = AdaptiveLimiter(f"{kind} …{(key or '')[-4:]}", **defaults.get(kind, {}))
        return _limiters[k]


# тяжёлые операции — не больше N одновременно (на весь процесс)
upload_slots = threading.BoundedSemaphore(12)
download_slots = threading.BoundedSemaphore(16)
chat_slots = threading.BoundedSemaphore(32)


class _Waiter:
    __slots__ = ("key", "tid", "tag", "t0", "event", "data", "next_at", "fails", "last_status", "busy")

    def __init__(self, key, tid, tag, t0):
        self.key, self.tid, self.tag, self.t0 = key, tid, tag, t0
        self.event, self.data = threading.Event(), None
        self.next_at = time.monotonic() + 6          # первые секунды задача точно не готова
        self.fails, self.last_status, self.busy = 0, "", False


class TaskPoller:
    """Один опросчик на все ожидающие задачи Polza (вместо цикла опроса в каждом потоке)."""

    def __init__(self, get_task, workers=12):
        self.get_task = get_task
        self.waiters, self.lock = {}, threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="poll")
        self.thread = None

    def _ensure(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, daemon=True, name="polza-poller")
            self.thread.start()

    def wait(self, key, tid, tag, t0, limit):
        """Ждёт завершения задачи. → ответ Polza или None (не дождались за limit секунд; ошибки опроса не фатальны)."""
        w = _Waiter(key, tid, tag, t0)
        with self.lock:
            self.waiters[tid] = w
        self._ensure()
        try:
            w.event.wait(limit)
            return w.data
        finally:
            with self.lock:
                self.waiters.pop(tid, None)

    def inflight(self):
        with self.lock:
            return len(self.waiters)

    def _loop(self):
        while True:
            now = time.monotonic()
            with self.lock:
                due = [w for w in self.waiters.values() if not w.busy and w.next_at <= now]
                for w in due:
                    w.busy = True
            for w in due:
                self.pool.submit(self._check, w)
            time.sleep(0.25)

    def _check(self, w):
        lim = limiter("poll", w.key)
        try:
            lim.acquire()
            data = self.get_task(w.key, w.tid)
            lim.on_ok()
            if w.fails:
                log.info("%s связь с Polza восстановлена после %d неудачных опросов", w.tag, w.fails)
            w.fails = 0
            st = data.get("status")
            if st != w.last_status:
                log.info("%s статус: %s → %s (%.0f с)", w.tag, w.last_status or "создана", st, time.time() - w.t0)
                w.last_status = st
            if st in ("completed", "failed", "cancelled"):
                w.data = data
                w.event.set()
                return
            age = time.time() - w.t0
            w.next_at = time.monotonic() + (4 if age < 120 else 8 if age < 600 else 15) + random.uniform(0, 1)
        except Exception as e:
            w.fails += 1
            if "429" in str(e) or "503" in str(e):
                lim.on_throttle()
            (log.warning if w.fails in (1, 5, 20) else log.debug)(
                "%s опрос статуса не удался (%d подряд): %s — продолжаю ждать", w.tag, w.fails, str(e)[:200])
            w.next_at = time.monotonic() + min(30, 4 * w.fails)
        finally:
            w.busy = False


def stats():
    with _lim_lock:
        items = list(_limiters.items())
    out = {}
    for (kind, key), lim in items:
        out.setdefault(key or "—", {})[kind] = lim.stats()
    return out
