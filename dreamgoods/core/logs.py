"""Логирование: консоль (INFO, с --debug — DEBUG) + файл logs/dreamgoods.log (всегда DEBUG, 5 МБ × 3)."""
import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime

from . import config

log = logging.getLogger("dreamgoods")


class _ConsoleFmt(logging.Formatter):
    COLORS = {"DEBUG": "\033[90m", "INFO": "", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[41m"}
    TAGS = {"DEBUG": "·", "INFO": " ", "WARNING": "!", "ERROR": "✖", "CRITICAL": "✖"}

    def __init__(self, color):
        super().__init__()
        self.color = color

    def format(self, r):
        t = datetime.fromtimestamp(r.created).strftime("%H:%M:%S")
        n = r.threadName
        th = ("раб-" + n.split("-", 1)[1] if n.startswith("worker-") else "веб" if "AnyIO" in n or "asyncio" in n
              else "main" if n == "MainThread" else n[:8])
        msg = f"[{t}] {self.TAGS.get(r.levelname, ' ')} {th:<8} {r.getMessage()}"
        if r.exc_info and r.levelno >= logging.ERROR and log.getEffectiveLevel() <= logging.DEBUG:
            msg += "\n" + "".join(traceback.format_exception(*r.exc_info)).rstrip()
        c = self.COLORS.get(r.levelname, "") if self.color else ""
        return f"{c}{msg}\033[0m" if c else msg


def setup_logging():
    debug = "--debug" in sys.argv
    if os.name == "nt":
        os.system("")   # включает цвета ANSI в консоли Windows 10+
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    log.setLevel(logging.DEBUG)
    log.propagate = False
    con = logging.StreamHandler(sys.stdout)
    con.setLevel(logging.DEBUG if debug else logging.INFO)
    con.setFormatter(_ConsoleFmt(color=sys.stdout.isatty() and "--no-color" not in sys.argv))
    log.addHandler(con)
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(config.LOG_DIR / "dreamgoods.log", maxBytes=5_000_000, backupCount=3,
                                                  encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)-12s %(message)s"))
        log.addHandler(fh)
    except Exception as e:
        log.warning("Не удалось открыть файл лога: %s", e)
    return debug


class Trace:
    """Метка для логов + накопитель расходов операции (пишутся в журнал расходов одной транзакцией)."""

    def __init__(self, tag):
        self.tag = tag
        self.usage = []

    def add(self, kind, model, cost, tokens=None, provider="", operation_id=None):
        from ..services.payments import operation_context
        self.usage.append({"managed": bool(operation_id or operation_context.get()), "kind": kind, "model": model or "", "cost": float(cost or 0), "tokens": tokens or {},
                           "provider": provider or ""})

    def __str__(self):
        return self.tag


def mb(n):
    return f"{n / 1_048_576:.1f} МБ"

