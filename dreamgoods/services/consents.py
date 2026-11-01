"""Документы и согласия: текущие версии документов, журнал согласий, повторное принятие новых версий.

Журнал согласий (consents) только пополняется: принятие и отзыв — отдельные записи с версией документа, временем,
IP и браузером. Это доказательная база для 152-ФЗ: кто, на какую редакцию документа и когда согласился.
"""
import csv
import io
from sqlalchemy import func, select

from .. import db
from ..core import legal as L
from ..core import mailer
from ..core.logs import log
from ..db.models import Consent, LegalDocument, Organization, User


def first_org_id(s):
    return s.scalar(select(Organization.id).order_by(Organization.id))


def seed(org_id):
    """Первый запуск: черновики документов версии 1 для видов, которых ещё нет."""
    with db.session() as s:
        have = set(s.scalars(select(LegalDocument.kind).where(LegalDocument.org_id == org_id)).all())
        added = 0
        for k in L.ORDER:
            if k not in have:
                title, required, _, _ = L.KINDS[k]
                s.add(LegalDocument(org_id=org_id, kind=k, version=1, title=title, body=L.DEFAULT_BODY.get(k, ""),
                                    required=required))
                added += 1
    if added:
        log.warning("Документы: созданы черновики (%d) — замените тексты в «Документах» мастер-аккаунта", added)


def current(s, org_id):
    """{kind: LegalDocument} — последние версии."""
    sub = (select(LegalDocument.kind, func.max(LegalDocument.version).label("v"))
           .where(LegalDocument.org_id == org_id).group_by(LegalDocument.kind).subquery())
    rows = s.scalars(select(LegalDocument).join(sub, (LegalDocument.kind == sub.c.kind) & (LegalDocument.version == sub.c.v))
                     .where(LegalDocument.org_id == org_id)).all()
    return {d.kind: d for d in rows}


def _brief(d):
    k = d.kind
    return {"kind": k, "title": d.title, "version": d.version, "required": d.required,
            "where": L.KINDS.get(k, ("", True, "register", "[" + d.title + "]"))[2],
            "label": L.KINDS.get(k, ("", True, "register", "[" + d.title + "]"))[3],
            "updated": d.created_at.isoformat() if d.created_at else None}


def registration_open(org):
    return bool((org.settings or {}).get("registration_open", True))


def public_list():
    """Для сайта: текущие документы и открыта ли регистрация."""
    with db.session() as s:
        org = s.get(Organization, first_org_id(s))
        docs = current(s, org.id) if org else {}
        return {"registration_open": registration_open(org) if org else False,
                "docs": [_brief(docs[k]) for k in L.ORDER if k in docs]}


def document(kind, version=None):
    with db.session() as s:
        org_id = first_org_id(s)
        q = select(LegalDocument).where(LegalDocument.org_id == org_id, LegalDocument.kind == kind)
        d = s.scalar(q.where(LegalDocument.version == int(version))) if version else \
            s.scalar(q.order_by(LegalDocument.version.desc()).limit(1))
        if not d:
            raise LookupError("документ не найден")
        return {**_brief(d), "body": d.body}


def record(s, org_id, user, kinds, source, ip="", agent="", granted=True, subject="", ref="", docs=None):
    """Запись согласий (или отзыва) в журнал. user — модель User или None."""
    docs = docs if docs is not None else current(s, org_id)
    for k in kinds:
        d = docs.get(k)
        s.add(Consent(org_id=org_id, user_id=getattr(user, "id", None), client_id=getattr(user, "client_id", None),
                      email=getattr(user, "email", "") or "", kind=k, doc_version=d.version if d else 0, granted=granted,
                      source=source, subject=subject[:300], ref=ref[:120], ip=(ip or "")[:64], agent=(agent or "")[:300]))


def _latest(s, user_id):
    """{kind: последняя запись} для согласий самого пользователя (без ref — не про модели)."""
    rows = s.scalars(select(Consent).where(Consent.user_id == user_id, Consent.ref == "").order_by(Consent.id)).all()
    out = {}
    for c in rows:
        out[c.kind] = c
    return out


def required_for(cu):
    """Обязательные документы регистрации, которые пользователь ещё не принял в текущей версии."""
    if cu.master:
        return []
    with db.session() as s:
        docs = current(s, cu.org_id)
        last = _latest(s, cu.id)
        need = []
        for k in L.REGISTER_KINDS:
            d = docs.get(k)
            if not d or not d.required:
                continue
            c = last.get(k)
            if not c or not c.granted or c.doc_version < d.version:
                need.append(_brief(d))
        return need


def mine(cu):
    """Для «Документы и согласия» в кабинете: каждый документ — версия и действующее согласие."""
    with db.session() as s:
        docs = current(s, cu.org_id)
        last = _latest(s, cu.id)
        out = []
        for k in L.REGISTER_KINDS:
            d = docs.get(k)
            if not d:
                continue
            c = last.get(k)
            out.append({**_brief(d), "granted": bool(c and c.granted), "granted_version": c.doc_version if c else 0,
                        "at": c.created_at.isoformat() if c and c.created_at else None})
        return out


def accept(cu, kinds, ip, agent, source="login"):
    kinds = [k for k in dict.fromkeys(kinds or []) if k in L.REGISTER_KINDS]
    if not kinds:
        raise ValueError("не выбрано ни одного документа")
    with db.session() as s:
        u = s.get(User, cu.id)
        record(s, cu.org_id, u, kinds, source, ip, agent)
    log.info("Согласия: %s принял(а) %s", cu.email, ", ".join(kinds))
    return mine(cu)


def revoke(cu, kind, ip, agent):
    """Отзыв согласия. Обязательные отзываются только запросом оператору (это прекращение пользования сервисом)."""
    if kind not in L.REGISTER_KINDS:
        raise LookupError("документ не найден")
    with db.session() as s:
        d = current(s, cu.org_id).get(kind)
        if d is not None and d.required:
            raise ValueError("Это обязательное согласие: без него сервис работать не может. Чтобы отозвать его и "
                             "удалить учётную запись, напишите оператору сервиса.")
        u = s.get(User, cu.id)
        record(s, cu.org_id, u, [kind], "account", ip, agent, granted=False)
    log.info("Согласия: %s отозвал(а) %s", cu.email, kind)
    return mine(cu)


def persona_photo(s, org_id, cu, persona, ip, agent, granted=True):
    """Подтверждение согласия человека на фото модели — в журнал (кто подтвердил, для какой модели)."""
    u = s.get(User, cu.id) if cu else None
    record(s, org_id, u, ["persona_photo"], "persona", ip, agent, granted=granted, subject=persona.name or "",
           ref=f"persona:{persona.id}")


# ───────── мастер ─────────

def admin_docs(cu):
    with db.session() as s:
        org = s.get(Organization, cu.org_id)
        rows = s.scalars(select(LegalDocument).where(LegalDocument.org_id == cu.org_id)
                         .order_by(LegalDocument.kind, LegalDocument.version.desc())).all()
        counts = dict(s.execute(select(Consent.kind, func.count(Consent.id)).where(Consent.org_id == cu.org_id,
                                                                                  Consent.granted.is_(True))
                                .group_by(Consent.kind)).all())
        by = {}
        for d in rows:
            by.setdefault(d.kind, []).append(d)
        docs = []
        for k in L.ORDER:
            vs = by.get(k) or []
            if not vs:
                continue
            d = vs[0]
            docs.append({**_brief(d), "body": d.body, "consents": counts.get(k, 0),
                         "versions": [{"version": v.version, "at": v.created_at.isoformat() if v.created_at else None}
                                      for v in vs]})
        return {"registration_open": registration_open(org), "docs": docs,
                "mail": mailer.configured()}


def admin_save(cu, kind, title, body, required):
    """Новая версия документа (если текст, название или обязательность изменились)."""
    if kind not in L.KINDS:
        raise LookupError("документ не найден")
    title = (title or "").strip()[:200] or L.title_of(kind)
    body = (body or "").strip()
    with db.session() as s:
        d = current(s, cu.org_id).get(kind)
        if d and d.title == title and d.body == body and d.required == bool(required):
            return admin_docs(cu)
        s.add(LegalDocument(org_id=cu.org_id, kind=kind, version=(d.version + 1) if d else 1, title=title, body=body,
                            required=bool(required), author_id=cu.id))
    log.warning("Документы: «%s» — новая версия (%s)", title, cu.email)
    return admin_docs(cu)


def set_registration(cu, open_):
    with db.session() as s:
        org = s.get(Organization, cu.org_id)
        org.settings = {**(org.settings or {}), "registration_open": bool(open_)}
    log.warning("Регистрация на сайте %s (%s)", "открыта" if open_ else "закрыта", cu.email)
    return admin_docs(cu)


def journal(cu, kind="", q="", limit=500):
    with db.session() as s:
        qq = select(Consent).where(Consent.org_id == cu.org_id)
        if kind:
            qq = qq.where(Consent.kind == kind)
        if q:
            qq = qq.where(Consent.email.ilike(f"%{q.strip()}%") | Consent.subject.ilike(f"%{q.strip()}%"))
        rows = s.scalars(qq.order_by(Consent.id.desc()).limit(limit)).all()
        return [{"id": c.id, "at": c.created_at.isoformat() if c.created_at else None, "email": c.email, "user_id": c.user_id,
                 "kind": c.kind, "title": L.title_of(c.kind), "version": c.doc_version, "granted": c.granted,
                 "source": c.source, "subject": c.subject, "ref": c.ref, "ip": c.ip, "agent": c.agent} for c in rows]


def journal_csv(cu, kind="", q=""):
    rows = journal(cu, kind, q, limit=100000)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "дата и время (UTC)", "логин", "документ", "версия", "действие", "где", "чьё согласие", "к чему",
                "IP", "браузер"])
    for r in rows:
        w.writerow([r["id"], r["at"], r["email"], r["title"], r["version"], "согласие" if r["granted"] else "отзыв",
                    r["source"], r["subject"], r["ref"], r["ip"], r["agent"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")
