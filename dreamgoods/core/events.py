"""Лента событий для интерфейса (память процесса; полный журнал — в logs/dreamgoods.log) и время запуска."""
import threading
from collections import deque
from datetime import datetime, timezone

from .logs import log


def utcnow():
    return datetime.now(timezone.utc)


STARTED_AT = utcnow()          # начало «сессии»: с этого момента считаются расходы «за сессию»

_lines = deque(maxlen=500)
_lock = threading.Lock()


def say(kind, text, project_id=None):
    """kind: info | ok | err. Пишет и в ленту интерфейса, и в журнал."""
    line = {"t": datetime.now().strftime("%H:%M:%S"), "kind": kind, "text": text, "project": project_id}
    with _lock:
        _lines.append(line)
    (log.error if kind == "err" else log.info)("%s", text)


def lines(project_id, limit=150, include_global=True):
    """Лента проекта; общие сообщения сервиса (project=None) — только мастеру."""
    allowed = (None, project_id) if include_global else (project_id,)
    with _lock:
        return [x for x in _lines if x["project"] in allowed][-limit:]
