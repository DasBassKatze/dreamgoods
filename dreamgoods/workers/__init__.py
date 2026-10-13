"""Фоновые задания: очередь в PostgreSQL и обработчики по видам заданий."""
from . import check, generate, persona, profile, resume, styleref, subcats
from .queue import (ACTIVE, HANDLERS, INSTANCE_ID, cancelled, enqueue, parallel, recover, register_instance, set_note,
                    set_parallel, start_workers, stop)


def _import(job_id):
    from .. import db
    from ..db.models import Job
    from ..services import importer
    with db.session() as s:
        sid = s.get(Job, job_id).payload["session"]
    importer.analyze(sid, job_id)


HANDLERS.update({"generate": generate.handle, "check": check.handle, "profile": profile.handle, "import": _import,
                 "persona": persona.handle, "subcats": subcats.handle, "styleref": styleref.handle})

__all__ = ["ACTIVE", "HANDLERS", "INSTANCE_ID", "cancelled", "enqueue", "parallel", "recover", "register_instance",
           "resume", "set_note", "set_parallel", "start_workers", "stop"]
