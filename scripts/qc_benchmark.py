"""Offline evaluation against reviewed examples; no paid model calls.
python scripts/qc_benchmark.py export output.json
python scripts/qc_benchmark.py evaluate output.json predictions.json
Predictions: [{"generation_id": 123, "pass": true}, ...]. Keep a held-out set.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def evaluate(examples, predictions):
    truth = {int(x["generation_id"]): x["accepted"] for x in examples}
    if len({int(x["generation_id"]) for x in predictions}) != len(predictions):
        raise ValueError("duplicate predictions")
    if any(type(x.get("pass")) is not bool for x in predictions):
        raise ValueError("prediction pass must be boolean")
    pred = {int(x["generation_id"]): x["pass"] for x in predictions}
    if truth.keys() != pred.keys():
        raise ValueError("predictions must cover exactly the benchmark set")
    bad = sum(not v for v in truth.values()); good = len(truth)-bad
    missed = sum(not v and pred[k] for k,v in truth.items())
    false = sum(v and not pred[k] for k,v in truth.items())
    return {"examples":len(truth), "missed_defects":missed, "false_rejections":false,
        "miss_rate": missed/bad if bad else None, "false_rejection_rate":false/good if good else None}


def export_examples():
    from sqlalchemy import select
    from dreamgoods import db
    from dreamgoods.db.models import Review, Generation, Frame, Product, ProductPhoto
    with db.session() as s:
        last = {}
        for review in s.scalars(select(Review).where(Review.generation_id.is_not(None)).order_by(Review.id)):
            last[review.generation_id] = review
        out = []
        for gid, review in last.items():
            g = s.get(Generation, gid)
            if not g or not g.output_asset_id:
                continue
            f = s.get(Frame, g.frame_id); p = s.get(Product, f.product_id)
            refs = list(s.scalars(select(ProductPhoto.asset_id).where(ProductPhoto.product_id == p.id,
                ProductPhoto.is_reference.is_(True))))
            out.append({"generation_id":gid, "accepted":review.verdict=="ok", "prompt":g.prompt,
                "asset":str(g.output_asset_id), "references":[str(x) for x in refs], "category":p.category,
                "comment":review.comment, "qc_original":review.ai_verdict})
        return out

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "evaluate"])
    parser.add_argument("dataset", type=Path)
    parser.add_argument("predictions", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action == "export":
        args.dataset.write_text(json.dumps(export_examples(), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if not args.predictions:
            parser.error("evaluate requires predictions.json")
        print(json.dumps(evaluate(json.loads(args.dataset.read_text()), json.loads(args.predictions.read_text())), indent=2))
