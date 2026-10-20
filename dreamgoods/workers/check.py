"""Задание «check»: ИИ-проверка уже готового кадра без новой генерации."""
from .. import db
from ..ai import qc
from ..core import storage
from ..core.events import say
from ..core.logs import Trace
from ..db.models import Frame, Generation, Job, Product, QCCheck
from ..services import moderation
from ..services.common import checklist_for, context, frame_status, write_usage
from .queue import set_note
from .refs import qc_refs


def handle(job_id):
    with db.session() as s:
        job = s.get(Job, job_id)
        frame = s.get(Frame, job.frame_id)
        product = s.get(Product, frame.product_id)
        project, org, st = context(s, product)
        if not frame.current_generation_id:
            raise RuntimeError("кадр ещё не сгенерирован")
        gen = s.get(Generation, frame.current_generation_id)
        out_asset = gen.output_asset
        st["qc_checklist"] = checklist_for(s, st, product, org.id)
        ids = dict(org=org.id, project=project.id, product=product.id, frame=frame.id, gen=gen.id)
        sku, pos, task = product.sku, frame.position, frame.prompt
    trace = Trace(f"[{sku} #{pos:02d}]")
    set_note(job_id, "проверка")
    res = qc.run_qc(st, task, qc_refs(ids["product"], st, ids, trace), storage.get(out_asset), trace)
    with db.session() as s:
        s.add(QCCheck(frame_id=ids["frame"], generation_id=ids["gen"], model=st.get("qc_model", ""), passed=res["pass"],
                      reasons=[x for x in res["defects"].split("; ") if x], tech=res["tech"], counts=res["counts"],
                      info=res["info"], cost_rub=res["cost"], source="check"))
        write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"check:{ids['gen']}")
        f = s.get(Frame, ids["frame"])
        if res.get("prohibited"):
            # запрещённое содержание на готовом кадре: версию прячем, кадр — снова «не снят»
            g = s.get(Generation, ids["gen"])
            g.status, g.outcome = "blocked", "rejected"
            if f.current_generation_id == ids["gen"]:
                f.current_generation_id, f.status = None, "missing"
        elif f.current_generation_id == ids["gen"]:
            f.status = frame_status(res)
    if res.get("prohibited"):
        moderation.record("frame", "проверка готового кадра", "image", res["prohibited"], "hidden", ids["project"],
                          ids["product"], ids["frame"])
        say("err", f"⛔ {sku} · кадр {pos:02d} · запрещённое содержание — кадр скрыт: {res['prohibited'][:160]}", ids["project"])
    elif res["pass"]:
        say("ok", f"🔍 {sku} · кадр {pos:02d} · проверка пройдена · {res['cost']:.2f} ₽", ids["project"])
    else:
        say("err", f"🔍 {sku} · кадр {pos:02d} · брак: {res['defects'][:200]}", ids["project"])
