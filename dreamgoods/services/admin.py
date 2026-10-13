"""Админ-панель: метрики качества, расходы (по видам, моделям, дням), баланс, очередь, журнал сервера."""
from collections import deque
from datetime import timedelta

from sqlalchemy import func, select

from .. import db
from ..ai import polza
from ..core import auth
from ..core import config
from ..core.events import STARTED_AT, utcnow
from ..core.settings import effective
from ..db.models import Frame, Generation, Job, Product, Project, UsageEntry, User
from ..workers import queue
from .common import org_of_project
from .metrics import metrics
from .presets import model_stats

KIND_RU = {"generation": "генерация кадров", "edit": "правки фото", "qc": "ИИ-проверка: сверка", "count": "ИИ-проверка: подсчёт",
           "spec": "ИИ-проверка: ожидания", "views": "ракурсы референсов", "profile": "профили товаров",
           "sort": "сортировка импорта", "persona": "модели клиента", "persona_image": "образы моделей", "style": "оформление"}


def overview(project_id):
    with db.session() as s:
        project = s.get(Project, project_id)
        org = org_of_project(s, project_id)
        st = effective(org, project)
        U = UsageEntry
        in_project = U.project_id == project_id
        total = lambda *w: float(s.scalar(select(func.coalesce(func.sum(U.amount_rub), 0)).where(*w)) or 0)
        spent_all = total(in_project)
        by_kind = [{"kind": k, "name": KIND_RU.get(k, k), "calls": n, "sum": round(float(c or 0), 2)}
                   for k, n, c in s.execute(select(U.kind, func.count(U.id), func.sum(U.amount_rub)).where(in_project)
                                            .group_by(U.kind).order_by(func.sum(U.amount_rub).desc())).all()]
        by_model = [{"model": m or "—", "calls": n, "sum": round(float(c or 0), 2), "avg": round(float(c or 0) / n, 3) if n else 0}
                    for m, n, c in s.execute(select(U.model, func.count(U.id), func.sum(U.amount_rub)).where(in_project)
                                             .group_by(U.model).order_by(func.sum(U.amount_rub).desc()).limit(20)).all()]
        since = utcnow() - timedelta(days=14)
        day = func.date_trunc("day", U.created_at)
        by_day = [{"day": d.date().isoformat(), "sum": round(float(c or 0), 2)}
                  for d, c in s.execute(select(day, func.sum(U.amount_rub)).where(in_project, U.created_at >= since)
                                        .group_by(day).order_by(day)).all()]
        gens = s.execute(select(func.count(Generation.id), func.coalesce(func.avg(Generation.cost_rub), 0),
                                func.coalesce(func.avg(Generation.seconds), 0))
                         .join(Frame, Frame.id == Generation.frame_id).join(Product, Product.id == Frame.product_id)
                         .where(Product.project_id == project_id, Generation.status == "ok")).one()
        pending = s.scalar(select(func.count(Generation.id)).join(Frame, Frame.id == Generation.frame_id)
                           .join(Product, Product.id == Frame.product_id)
                           .where(Product.project_id == project_id, Generation.status == "pending"))
        errors_24h = s.scalar(select(func.count(Job.id)).where(Job.project_id == project_id, Job.status.in_(("error", "dismissed")),
                                                               Job.finished_at >= utcnow() - timedelta(days=1)))
        met = metrics(s, project_id, spent_all)
        org_all = total(U.org_id == org.id)
        session = total(in_project, U.created_at >= STARTED_AT)
        weak = any(auth.check_password("admin", h) for h in s.scalars(select(User.password_hash)
                                                                       .where(User.role == "master", User.active.is_(True))).all())
        stats = model_stats(s, org.id)
    b = polza.balance(st.get("api_key"))
    return {"balance": b["value"], "balance_error": b["error"],
            "spent": {"session": round(session, 2), "project": round(spent_all, 2), "org": round(org_all, 2)},
            "by_kind": by_kind, "by_model": by_model, "by_day": by_day,
            "generations": {"count": gens[0], "avg_cost": round(float(gens[1]), 2), "avg_seconds": round(float(gens[2]))},
            "model_stats": stats, "pending": pending or 0, "errors_24h": errors_24h or 0, "metrics": met,
            "queue": {"parallel": queue.parallel(), "max": queue.MAX_WORKERS},
            "model": {"model": st.get("model"), "providers": st.get("providers"), "resolution": st.get("resolution"),
                      "aspect": st.get("aspect"), "qc_model": st.get("qc_model")},
            "default_password": weak}


def log_tail(lines=300, level=""):
    path = config.LOG_DIR / "dreamgoods.log"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        tail = deque(fh, maxlen=max(50, min(3000, lines)) * (4 if level else 1))
    out = [x.rstrip("\n") for x in tail]
    if level:
        out = [x for x in out if f" {level.upper()}" in x or (level == "warning" and " ERROR" in x)]
    return out[-lines:]
