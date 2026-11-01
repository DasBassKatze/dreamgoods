from sqlalchemy import select, func, cast, String, or_
from .. import db
from ..db.models import Frame, Generation, Product, ProductPhoto, QCCheck


def listing(project_id, page=1, status="review", defect="", query=""):
    with db.session() as s:
        q = select(Frame, Product, Generation).join(Product, Product.id == Frame.product_id).join(Generation,
            Generation.id == Frame.current_generation_id).where(Product.project_id == project_id, Frame.status != "retired")
        if status != "all":
            q = q.where(Frame.status == status)
        if query:
            term = "%" + query.replace("%", "\\%").replace("_", "\\_") + "%"
            q = q.where(or_(Product.sku.ilike(term, escape="\\"), Product.name.ilike(term, escape="\\")))
        latest_qc = select(QCCheck.id).where(QCCheck.generation_id == Generation.id).order_by(QCCheck.id.desc()).limit(1).correlate(Generation).scalar_subquery()
        if defect:
            q = q.where(select(QCCheck.id).where(QCCheck.id == latest_qc,
                func.replace(cast(QCCheck.info, String), ' ', '').contains('"category":"' + defect + '"')).exists())
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        out = []
        for f, p, g in s.execute(q.order_by(Product.sku, Frame.position).offset((page-1)*24).limit(24)):
            check = s.scalar(select(QCCheck).where(QCCheck.generation_id == g.id).order_by(QCCheck.id.desc()).limit(1))
            refs = list(s.scalars(select(ProductPhoto.asset_id).where(ProductPhoto.product_id == p.id,
                ProductPhoto.is_reference.is_(True)).order_by(ProductPhoto.position).limit(6)))
            out.append({"id": f.id, "product_id": p.id, "sku": p.sku, "position": f.position,
                "generation": g.id, "asset": str(g.output_asset_id), "status": f.status,
                "references": [str(a) for a in refs], "defects": check.reasons if check else [],
                "details": (check.info or {}).get("defects", []) if check else []})
        return {"items": out, "total": total, "page": page, "page_size": 24}
