from decimal import Decimal
from sqlalchemy import func, select
from .. import db
from ..core import presets
from ..db.models import Frame, Generation, Product, Project, Organization, QCCheck, UsageEntry
from .common import context
from .billing import markup_of
from .payments import estimate_call, held, money


def preview(project_id, frame_ids):
    with db.session() as s:
        project = s.get(Project, project_id)
        client = project.client
        org = s.get(Organization, client.org_id)
        markup = Decimal(str(markup_of(client, org)))
        lines, generation, checking, upper = [], Decimal(0), Decimal(0), Decimal(0)
        rows = s.execute(select(Frame, Product).join(Product, Product.id == Frame.product_id)
            .where(Product.project_id == project_id, Frame.id.in_(frame_ids))).all()
        groups = {}
        for f, p in rows:
            st = context(s, p)[2]
            st = presets.model_for(st, presets.BLOCK_OF_PROMPT.get(f.block, ""), f.model)
            model = st["model"]
            avg, high, samples = estimate_call(s, org.id, model, "generation")
            category = p.category or ""
            history = s.execute(select(Generation.cost_rub).join(Frame, Frame.id == Generation.frame_id)
                .join(Product, Product.id == Frame.product_id).join(Project, Project.id == Product.project_id)
                .where(Project.client_id == client.id, Generation.model == model, Generation.status == "ok",
                    Frame.block == f.block, Product.category == category, Generation.cost_rub > 0)
                .order_by(Generation.id.desc()).limit(100)).scalars().all()
            if history:
                avg = money(sum(map(Decimal, map(str, history))) / len(history))
            qc_avg, qc_high, _ = estimate_call(s, org.id, st.get("qc_model", ""), "qc")
            qc_n = (3 if st.get("qc_count") else 1) if st.get("qc_enabled") else 0
            tries = 1 + (int(st.get("qc_retries") or 0) if st.get("qc_enabled") and st.get("qc_autoregen") else 0)
            generation += avg * markup
            checking += qc_avg * qc_n * markup
            upper += (high + qc_high * qc_n) * tries * markup
            key = (model, f.block, category)
            v = groups.setdefault(key, {"model": model, "block": f.block, "category": category,
                "frames": 0, "samples": len(history) or samples, "source": "history" if history or samples else "fallback"})
            v["frames"] += 1
        for v in groups.values():
            lines.append(v)
        complete = s.scalar(select(func.count(Product.id)).where(Product.project_id == project_id,
            ~select(Frame.id).where(Frame.product_id == Product.id, Frame.status != "retired",
                (Frame.status.not_in(("pass", "accepted")) | Frame.current_generation_id.is_(None))).exists(),
            select(Frame.id).where(Frame.product_id == Product.id, Frame.status != "retired").exists())) or 0
        accepted = s.scalar(select(func.count(Frame.id)).join(Product).where(Product.project_id == project_id,
            Frame.status.in_(("pass", "accepted")), Frame.current_generation_id.is_not(None))) or 0
        spent = Decimal(str(s.scalar(select(func.coalesce(func.sum(UsageEntry.amount_rub), 0)).where(UsageEntry.project_id == project_id)) or 0)) * markup
        return {"count": len(rows), "products": len({p.id for _, p in rows}), "generation": float(money(generation)),
            "checking": float(money(checking)), "expected": float(money(generation + checking)),
            "upper": float(money(upper)), "groups": lines, "reserved": float(held(s, client.id)),
            "available": float(money(client.balance_rub) - held(s, client.id)),
            "accepted_frames": accepted, "complete_products": complete,
            "cost_per_accepted": float(money(spent / accepted)) if accepted else None,
            "cost_per_complete": float(money(spent / complete)) if complete else None,
            "note": "Оценка, не тариф. Резерв проверяется перед каждым платным запросом. Фактическая цена провайдера может отличаться."}
