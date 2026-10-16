"""Отчёт сервиса за период (мастер): деньги клиентов, себестоимость Polza, наценка, объём работы — сводка,
по пользователям, по видам операций, по моделям и по дням. Выгрузка в CSV для бухгалтерии."""
import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, literal_column, select

from .. import db
from ..db.models import BalanceEntry, Client, Frame, Generation, Job, Product, Project, QCCheck, UsageEntry
from .admin import KIND_RU

TZ = ZoneInfo("Europe/Moscow")          # границы дней — по московскому времени
MAX_DAYS = 1100


def _bounds(date_from, date_to):
    d1 = date.fromisoformat(date_from) if date_from else date.today().replace(day=1)
    d2 = date.fromisoformat(date_to) if date_to else date.today()
    if d2 < d1:
        raise ValueError("дата «по» раньше даты «с»")
    if (d2 - d1).days > MAX_DAYS:
        raise ValueError("слишком длинный период — не больше трёх лет")
    return d1, d2, datetime.combine(d1, time(), TZ), datetime.combine(d2 + timedelta(days=1), time(), TZ)


def build(cu, date_from=None, date_to=None, client_id=None, usn_rate=0.06):
    d1, d2, t1, t2 = _bounds(date_from, date_to)
    with db.session() as s:
        clients = {c.id: c for c in s.scalars(select(Client).where(Client.org_id == cu.org_id)).all()}
        ids = [int(client_id)] if client_id else list(clients)
        if client_id and int(client_id) not in clients:
            raise LookupError("пользователь не найден")
        ids = ids or [0]
        B = BalanceEntry
        in_b = [B.client_id.in_(ids), B.created_at >= t1, B.created_at < t2]
        # деньги по журналу баланса
        money = {}
        for cid, kind, amt, cost, n in s.execute(
                select(B.client_id, B.kind, func.sum(B.amount_rub), func.sum(B.cost_rub), func.count(B.id))
                .where(*in_b).group_by(B.client_id, B.kind)).all():
            m = money.setdefault(cid, {"topup": 0.0, "adjust": 0.0, "charge": 0.0, "charge_cost": 0.0, "charges": 0})
            if kind == "charge":
                m["charge"] += -float(amt or 0)
                m["charge_cost"] += float(cost or 0)
                m["charges"] += n
            elif kind == "topup":
                m["topup"] += float(amt or 0)
            else:
                m["adjust"] += float(amt or 0)
        # остатки на балансах на конец периода — последняя запись журнала у каждого
        last = dict(s.execute(select(B.client_id, func.max(B.id)).where(B.client_id.in_(ids), B.created_at < t2)
                              .group_by(B.client_id)).all())
        bal_end = {cid: float(s.get(B, eid).balance_after or 0) for cid, eid in last.items()}
        # себестоимость Polza — весь расход, в т.ч. проекты мастера и кабинеты без баланса
        U = UsageEntry
        in_u = [U.org_id == cu.org_id, U.created_at >= t1, U.created_at < t2]
        if client_id:
            in_u.append(Project.client_id == int(client_id))
        uq = lambda *cols: select(*cols).select_from(U).outerjoin(Project, Project.id == U.project_id).where(*in_u)
        usage_by_client = {cid: float(v or 0) for cid, v in s.execute(uq(Project.client_id, func.sum(U.amount_rub))
                                                                      .group_by(Project.client_id)).all()}
        by_kind = [{"kind": k, "name": KIND_RU.get(k, k), "calls": n, "cost": round(float(c or 0), 2)}
                   for k, n, c in s.execute(uq(U.kind, func.count(U.id), func.sum(U.amount_rub))
                                            .group_by(U.kind).order_by(func.sum(U.amount_rub).desc())).all()]
        by_model = [{"model": m or "—", "calls": n, "cost": round(float(c or 0), 2),
                     "avg": round(float(c or 0) / n, 3) if n else 0}
                    for m, n, c in s.execute(uq(U.model, func.count(U.id), func.sum(U.amount_rub))
                                             .group_by(U.model).order_by(func.sum(U.amount_rub).desc())).all()]
        # объём работы: кадры и правки, проверки, ошибки
        G = Generation
        is_edit = case((func.coalesce(G.instruction, "") != "", 1), else_=0)
        gq = (select(Project.client_id, func.count(G.id), func.sum(is_edit)).select_from(G)
              .join(Frame, Frame.id == G.frame_id).join(Product, Product.id == Frame.product_id)
              .join(Project, Project.id == Product.project_id)
              .where(G.status == "ok", G.created_at >= t1, G.created_at < t2, Project.client_id.in_(ids))
              .group_by(Project.client_id))
        work = {cid: {"images": n, "edits": int(e or 0)} for cid, n, e in s.execute(gq).all()}
        qc_n = s.scalar(select(func.count(QCCheck.id)).select_from(QCCheck)
                        .join(Frame, Frame.id == QCCheck.frame_id).join(Product, Product.id == Frame.product_id)
                        .join(Project, Project.id == Product.project_id)
                        .where(QCCheck.created_at >= t1, QCCheck.created_at < t2, Project.client_id.in_(ids))) or 0
        errors = s.scalar(select(func.count(Job.id)).select_from(Job).join(Project, Project.id == Job.project_id)
                          .where(Job.status.in_(("error", "dismissed")), Job.finished_at >= t1, Job.finished_at < t2,
                                 Project.client_id.in_(ids))) or 0
        # по дням (московское время)
        local = lambda col: func.date(func.timezone(literal_column("'Europe/Moscow'"), col))
        days = {}
        for d, kind, amt, cost in s.execute(select(local(B.created_at), B.kind, func.sum(B.amount_rub), func.sum(B.cost_rub))
                                            .where(*in_b).group_by(local(B.created_at), B.kind)).all():
            r = days.setdefault(d, {"topup": 0.0, "charge": 0.0, "cost": 0.0, "images": 0})
            if kind == "charge":
                r["charge"] += -float(amt or 0)
            elif kind == "topup":
                r["topup"] += float(amt or 0)
        for d, c in s.execute(uq(local(U.created_at), func.sum(U.amount_rub)).group_by(local(U.created_at))).all():
            days.setdefault(d, {"topup": 0.0, "charge": 0.0, "cost": 0.0, "images": 0})["cost"] += float(c or 0)
        for d, n in s.execute(select(local(G.created_at), func.count(G.id)).select_from(G)
                              .join(Frame, Frame.id == G.frame_id).join(Product, Product.id == Frame.product_id)
                              .join(Project, Project.id == Product.project_id)
                              .where(G.status == "ok", G.created_at >= t1, G.created_at < t2, Project.client_id.in_(ids))
                              .group_by(local(G.created_at))).all():
            days.setdefault(d, {"topup": 0.0, "charge": 0.0, "cost": 0.0, "images": 0})["images"] += n

    rows = []
    for cid in sorted(set(money) | set(usage_by_client) | set(work), key=lambda x: (x is None, (clients.get(x).name if x in clients else ""))):
        if cid is not None and cid not in clients:
            continue
        m = money.get(cid, {})
        c = clients.get(cid)
        rows.append({"client_id": cid, "client": c.name if c else "без проекта", "billing": bool(c and c.billing),
                     "topup": round(m.get("topup", 0), 2), "adjust": round(m.get("adjust", 0), 2),
                     "charged": round(m.get("charge", 0), 2), "charged_cost": round(m.get("charge_cost", 0), 2),
                     "margin": round(m.get("charge", 0) - m.get("charge_cost", 0), 2),
                     "polza": round(usage_by_client.get(cid, 0), 2),
                     "images": work.get(cid, {}).get("images", 0), "edits": work.get(cid, {}).get("edits", 0),
                     "balance_end": round(bal_end.get(cid, 0), 2) if c and c.billing else None})
    tot = lambda k: round(sum(r[k] or 0 for r in rows), 2)
    topups, charged, charged_cost, polza_all = tot("topup"), tot("charged"), tot("charged_cost"), tot("polza")
    summary = {
        "topups": topups, "adjust": tot("adjust"), "charged": charged, "charged_cost": charged_cost,
        "margin": round(charged - charged_cost, 2), "markup": round(charged / charged_cost, 2) if charged_cost else None,
        "polza": polza_all, "polza_unbilled": round(max(0.0, polza_all - charged_cost), 2),
        "result": round(charged - polza_all, 2),
        "balances_end": round(sum(r["balance_end"] or 0 for r in rows), 2),
        "images": sum(r["images"] for r in rows), "edits": sum(r["edits"] for r in rows), "checks": qc_n, "errors": errors,
        "clients_paying": sum(1 for r in rows if r["charged"] > 0),
        "usn_rate": usn_rate, "usn_tax": round(topups * usn_rate, 2),
    }
    by_day = [{"day": d.isoformat(), **{k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()}}
              for d, r in sorted(days.items())]
    return {"from": d1.isoformat(), "to": d2.isoformat(), "client_id": int(client_id) if client_id else None,
            "summary": summary, "clients": rows, "by_kind": by_kind, "by_model": by_model, "by_day": by_day,
            "client_list": [{"id": c.id, "name": c.name} for c in sorted(clients.values(), key=lambda c: c.name.lower())]}


def to_csv(rep):
    """CSV для Excel: разделитель «;», запятая в дробях, UTF-8 с BOM. Разделы идут друг под другом."""
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    n = lambda v: "" if v is None else (f"{v:.2f}".replace(".", ",") if isinstance(v, float) else v)
    s = rep["summary"]
    w.writerow([f"Отчёт DreamGoods за период {rep['from']} — {rep['to']}"])
    w.writerow([])
    w.writerow(["Сводка", "Значение"])
    for label, key in [("Пополнения балансов (поступило от клиентов), ₽", "topups"), ("Корректировки балансов, ₽", "adjust"),
                       ("Списано с балансов за услуги, ₽", "charged"), ("Себестоимость Polza по списаниям, ₽", "charged_cost"),
                       ("Наценка (списано − себестоимость), ₽", "margin"), ("Весь расход Polza за период, ₽", "polza"),
                       ("Расход Polza без оплаты клиентом (мастер, кабинеты без баланса), ₽", "polza_unbilled"),
                       ("Итог: списано − весь расход Polza, ₽", "result"), ("Остаток на балансах на конец периода, ₽", "balances_end"),
                       ("Сгенерировано изображений", "images"), ("Из них правок", "edits"), ("ИИ-проверок", "checks"),
                       ("Ошибок заданий", "errors"), ("Платящих пользователей", "clients_paying"),
                       (f"Оценка налога {s['usn_rate'] * 100:g}% с пополнений, ₽", "usn_tax")]:
        w.writerow([label, n(float(s[key])) if isinstance(s[key], (int, float)) and key not in ("images", "edits", "checks", "errors", "clients_paying") else s[key]])
    w.writerow([])
    w.writerow(["По пользователям"])
    w.writerow(["Пользователь", "Пополнения", "Корректировки", "Списано", "Себестоимость списаний", "Наценка", "Весь расход Polza",
                "Изображений", "Правок", "Остаток на конец"])
    for r in rep["clients"]:
        w.writerow([r["client"], n(r["topup"]), n(r["adjust"]), n(r["charged"]), n(r["charged_cost"]), n(r["margin"]),
                    n(r["polza"]), r["images"], r["edits"], n(r["balance_end"])])
    w.writerow([])
    w.writerow(["По видам операций"])
    w.writerow(["Операция", "Запросов", "Себестоимость Polza"])
    for r in rep["by_kind"]:
        w.writerow([r["name"], r["calls"], n(r["cost"])])
    w.writerow([])
    w.writerow(["По моделям"])
    w.writerow(["Модель", "Запросов", "Себестоимость Polza", "Средняя цена запроса"])
    for r in rep["by_model"]:
        w.writerow([r["model"], r["calls"], n(r["cost"]), n(float(r["avg"]))])
    w.writerow([])
    w.writerow(["По дням"])
    w.writerow(["Дата", "Пополнения", "Списано", "Расход Polza", "Изображений"])
    for r in rep["by_day"]:
        w.writerow([r["day"], n(float(r["topup"])), n(float(r["charge"])), n(float(r["cost"])), r["images"]])
    return "﻿" + out.getvalue()
