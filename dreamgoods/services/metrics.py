"""Метрики из диздока: прохождение с первой попытки (по моделям), ручная очередь, точность проверки по разметке,
цена принятого кадра, цена проверки."""
from sqlalchemy import and_, func, select

from ..db.models import Frame, Generation, Product, QCCheck, Review, UsageEntry


def _pct(a, b):
    return round(a / b * 100) if b else None


def metrics(s, project_id, spent_all):
    frames = s.execute(select(Frame.status).join(Product, Product.id == Frame.product_id)
                       .join(Generation, Generation.id == Frame.current_generation_id)
                       .where(Product.project_id == project_id)).scalars().all()
    checked = sum(1 for st in frames if st in ("pass", "review", "accepted"))
    review = sum(1 for st in frames if st == "review")
    accepted = sum(1 for st in frames if st in ("pass", "accepted"))

    first = s.execute(select(Generation.model, QCCheck.passed)
                      .join(QCCheck, and_(QCCheck.generation_id == Generation.id, QCCheck.source == "gen"))
                      .join(Frame, Frame.id == Generation.frame_id).join(Product, Product.id == Frame.product_id)
                      .where(Product.project_id == project_id, Generation.attempt == 1)).all()
    by_model = {}
    for m, passed in first:
        v = by_model.setdefault(m or "?", [0, 0])
        v[0] += 1
        v[1] += bool(passed)
    gen_n = sum(v[0] for v in by_model.values())
    fp = sum(v[1] for v in by_model.values())

    # разметка: последнее ручное решение по каждой генерации против вердикта ИИ
    revs = s.execute(select(Review.generation_id, Review.verdict, Review.ai_verdict, Review.id)
                     .join(Frame, Frame.id == Review.frame_id).join(Product, Product.id == Frame.product_id)
                     .where(Product.project_id == project_id).order_by(Review.id)).all()
    last = {}
    for gid, verdict, ai, rid in revs:
        last[gid or -rid] = (verdict, ai)
    lab = [v for v in last.values() if v[1] in ("pass", "fail")]
    missed = sum(1 for v, ai in lab if ai == "pass" and v == "bad")
    false_rej = sum(1 for v, ai in lab if ai == "fail" and v == "ok")
    bad_total = sum(1 for v, _ in lab if v == "bad")
    good_total = sum(1 for v, _ in lab if v == "ok")

    usage = s.execute(select(UsageEntry.kind, func.count(UsageEntry.id), func.sum(UsageEntry.amount_rub))
                      .where(UsageEntry.project_id == project_id, UsageEntry.kind.in_(("qc", "count", "spec", "views")))
                      .group_by(UsageEntry.kind)).all()
    names = {"qc": "сверка", "count": "подсчёт", "spec": "ожидания", "views": "ракурсы референсов"}
    qc_calls = sum(n for k, n, _ in usage if k == "qc")
    qc_cost = sum(float(c or 0) for _, _, c in usage)
    return {"qc_per_frame": round(qc_cost / qc_calls, 3) if qc_calls else None,
            "qc_passes": [{"what": names[k], "calls": n, "avg": round(float(c or 0) / n, 3) if n else 0}
                          for k, n, c in usage],
            "checked": checked, "generated": gen_n, "first_pass": _pct(fp, gen_n), "review": review,
            "review_share": _pct(review, checked), "accepted": accepted,
            "cost_per_accepted": round(spent_all / accepted, 2) if accepted else None,
            "by_model": [{"model": m, "n": v[0], "first_pass": _pct(v[1], v[0])} for m, v in by_model.items()],
            "labeled": len(lab), "caught": _pct(bad_total - missed, bad_total), "missed": missed,
            "false_rej": false_rej, "false_rej_pct": _pct(false_rej, good_total)}
