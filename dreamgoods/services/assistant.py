"""Read-only assistant: bounded context, validated navigation, existing paid-call ledger."""
import json
import threading
from contextlib import contextmanager

from sqlalchemy import select

from .. import db
from ..ai import polza
from ..ai.assistant_guide import GUIDE, ROUTES, SYSTEM
from ..core.events import utcnow
from ..core.logs import Trace, log
from ..db.models import Job, Product, Project
from ..services import payments, projects
from ..workers.queue import INSTANCE_ID

_lock = threading.Lock()
_active = set()
_slots = threading.BoundedSemaphore(3)


class Busy(ValueError):
    status = 429


@contextmanager
def single_request(user_id):
    with _lock:
        if user_id in _active or not _slots.acquire(blocking=False):
            raise Busy("Помощник уже отвечает. Дождитесь завершения и попробуйте снова.")
        _active.add(user_id)
    try:
        yield
    finally:
        with _lock:
            _active.discard(user_id)
            _slots.release()


def routes(master):
    return {k: v for k, v in ROUTES.items() if master or not k.startswith("m-")}


def config(pid, master):
    st = projects.project_settings(pid)
    return {"enabled": st.get("assistant_enabled", True), "configured": bool(st.get("api_key")),
            "model": st.get("assistant_model") or "openai/gpt-4.1-mini", "routes": routes(master)}


def validate_reply(raw, master, selected):
    if not isinstance(raw, dict) or not isinstance(raw.get("answer"), str) or not raw["answer"].strip():
        raise ValueError("Помощник вернул пустой ответ. Попробуйте переформулировать вопрос.")
    out, seen = [], set()
    actions = raw.get("actions") if isinstance(raw.get("actions"), list) else []
    for a in actions[:10]:
        if not isinstance(a, dict):
            continue
        if a.get("type") == "navigate" and isinstance(a.get("route"), str) and a["route"] in routes(master):
            key = ("navigate", a["route"])
            item = {"type": "navigate", "route": a["route"], "label": ROUTES[a["route"]]}
        elif a.get("type") == "product" and type(a.get("product_id")) is int and a["product_id"] in selected:
            key = ("product", a["product_id"])
            item = {"type": "product", "product_id": a["product_id"], "label": "Открыть профиль товара"}
        else:
            continue
        if key not in seen:
            out.append(item); seen.add(key)
        if len(out) == 3:
            break
    return {"answer": raw["answer"].strip()[:10000], "actions": out}


def reply(pid, user, body):
    with single_request(user.id):
        st = projects.project_settings(pid)
        if not st.get("assistant_enabled", True):
            raise ValueError("Помощник выключен в технических настройках проекта.")
        if not st.get("api_key"):
            raise ValueError("Для помощника нужен ключ Polza. Добавьте его в разделе «Ключи Polza» или обратитесь к администратору.")
        model = st.get("assistant_model") or "openai/gpt-4.1-mini"
        with db.session() as s:
            project = s.get(Project, pid, with_for_update=True)
            if not project or project.archived:
                raise LookupError("Проект не найден")
            products = s.scalars(select(Product).where(Product.project_id == pid,
                Product.id.in_(body.product_ids)).order_by(Product.id)).all() if body.product_ids else []
            selected = {p.id for p in products}
            if selected != set(body.product_ids):
                raise LookupError("Выбранный товар не найден в этом проекте")
            context = {"project": project.name[:120], "current_route": body.route,
                       "allowed_routes": routes(user.master),
                       "selected_products": [{"id": p.id, "sku": p.sku, "name": p.name,
                                              "category": p.category, "has_profile": bool(p.current_profile_id)} for p in products]}
            # No prompts, keys, images, conversation text or settings are persisted in the job.
            job = Job(project_id=pid, kind="assistant", status="running", worker=f"{INSTANCE_ID}/assistant",
                      started_at=utcnow(), payload={"by_master": user.master}, note="Ответ помощника")
            s.add(job); s.flush(); jid = job.id
        token = payments.job_context.set(jid)
        try:
            content = json.dumps({"context": context, "history": [m.model_dump() for m in body.history],
                                  "question": body.message}, ensure_ascii=False)
            # Assistant always uses the project's main Polza key, independently of local QC endpoints.
            endpoint = {**st, "qc_base_url": "", "qc_api_key": st["api_key"]}
            raw, cost, _ = polza.chat(endpoint, model, SYSTEM + "\nСправка:\n" + GUIDE, content,
                                      Trace("[помощник]"), "assistant", max_tokens=1800,
                                      reasoning="none", _retry=False)
            result = validate_reply(raw, user.master, selected)
            with db.session() as s:
                job = s.get(Job, jid); job.status = "done"; job.finished_at = utcnow()
            return {**result, "model": model, "cost_rub": cost}
        except Exception as exc:
            with db.session() as s:
                job = s.get(Job, jid)
                if job:
                    job.status = "error"; job.error = "Не удалось получить ответ помощника"; job.finished_at = utcnow()
            if isinstance(exc, (payments.BudgetPause, ValueError)):
                raise
            log.warning("Помощник: запрос %s не завершён (%s)", jid, type(exc).__name__)
            raise ValueError("Не удалось получить ответ ИИ. Проверьте ключ и доступность модели. При обрыве связи проверьте операцию в «Бюджетах» перед повтором.") from exc
        finally:
            payments.job_context.reset(token)
