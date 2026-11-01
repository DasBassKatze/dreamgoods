"""Задание «generate»: генерация кадра → ИИ-проверка → автоперегенерация брака с описанием дефектов."""
import time
import traceback

from .. import db
from ..ai import persona as personas
from ..ai import prompts as P
from ..ai import styleref
from ..ai import polza, qc
from ..ai.images import ref_payload
from ..core import presets as presets_core
from ..core import storage
from ..core.events import say
from ..core.logs import Trace, log
from ..db.models import Frame, Generation, Job, Product, QCCheck
from ..services import billing, payments
from ..services.common import checklist_for, context, frame_status, write_usage
from .queue import cancelled, set_note
from .refs import persona_for, qc_refs, ref_photos, style_for


def handle(job_id):
    with db.session() as s:
        job = s.get(Job, job_id)
        frame = s.get(Frame, job.frame_id)
        product = s.get(Product, frame.product_id)
        project, org, st = context(s, product)
        key = st.get("api_key")
        if not key:
            raise RuntimeError("не указан API-ключ Polza (Настройки)")
        photos = ref_photos(s, product, int(st.get("max_refs") or 6))
        if not photos:
            raise RuntimeError("не выбрано ни одного фото-референса")
        st["qc_checklist"] = checklist_for(s, st, product, org.id)
        ids = dict(org=org.id, project=project.id, product=product.id, frame=frame.id)
        sku, pos, base_prompt, prev_gen = product.sku, frame.position, frame.prompt, frame.current_generation_id
        # модель генерации: своя у ручного метода → модель блока пресета → общая (не стреляем из пушки по воробьям)
        st = presets_core.model_for(st, presets_core.BLOCK_OF_PROMPT.get(P.block_of(base_prompt), ""), frame.model)
        comment = (job.payload or {}).get("comment", "")
        edit = ((job.payload or {}).get("edit") or "").strip()     # правка готового фото по промпту
        source_gen, source_asset = None, None
        if edit:
            source_gen = int((job.payload or {}).get("source") or prev_gen or 0)
            sg = s.get(Generation, source_gen) if source_gen else None
            if not sg or sg.frame_id != frame.id or not sg.output_asset_id:
                raise RuntimeError("нет исходной картинки для правки — сначала сгенерируйте кадр")
            source_asset = sg.output_asset
        ref_assets = [p.asset for p in photos]
        if edit:
            ref_assets = ref_assets[:4]   # для правки фото товара нужны только как сверка — хватит четырёх
        persona, persona_assets = (persona_for(s, product, st) if personas.has_person(base_prompt) and not edit
                                   else (None, []))
        persona_name, persona_desc = (persona.name, persona.description) if persona else ("", "")
        persona_style = dict(persona.style or {}) if persona else {}
        sref, style_assets = style_for(s, product, st) if not edit else (None, [])
        if sref and not styleref.applies(P.block_of(base_prompt), sref.blocks, "main marketplace cover" in base_prompt.lower()):
            sref, style_assets = None, []
        style_name, style_desc, style_note = (sref.name, sref.description, sref.note) if sref else ("", "", "")
    trace = Trace(f"[{sku} #{pos:02d}]")
    side = int(st.get("ref_side") or 1536)
    refs = [ref_payload(storage.get(a), side) for a in ref_assets]
    persona_refs = [ref_payload(storage.get(a), side) for a in persona_assets]
    if persona_refs:
        log.info("%s модель клиента «%s»: фото %d", trace, persona_name, len(persona_refs))
    style_refs = [ref_payload(storage.get(a), side) for a in style_assets]
    if style_refs:
        log.info("%s оформление «%s»: фото %d", trace, style_name, len(style_refs))
    if edit:   # фото 1 — текущая версия кадра в полном размере, дальше — фото товара
        refs = [ref_payload(storage.get(source_asset), max(side, 2048))] + refs
        log.info("%s ✏ правка версии #%s: %s", trace, source_gen, edit)

    def full_prompt(p):
        if edit:
            return p
        p = styleref.apply(p, len(refs), len(persona_refs), len(style_refs), style_desc, style_note)
        return personas.apply(p, persona_desc, len(refs), len(persona_refs), persona_style)
    qc_on = bool(st.get("qc_enabled"))
    check_refs = qc_refs(ids["product"], st, ids, trace) if qc_on else []
    regen = qc_on and bool(st.get("qc_autoregen", True))
    tries = 1 + (max(0, int(st.get("qc_retries") or 0)) if regen else 0)
    log.info("%s модель %s · референсы %d · проверка %s · попыток до %d", trace, st["model"], len(refs),
             "вкл" if qc_on else "выкл", tries)

    first_prompt = P.edit_prompt(edit, len(refs) - 1, personas.has_person(base_prompt)) if edit else base_prompt
    prompt = qc.correction(first_prompt, comment) if comment else first_prompt
    if comment:
        log.info("%s в промпт добавлено ваше замечание: %s", trace, comment)
    attempts, error, t0, total = [], None, time.time(), 0.0
    for a in range(1, tries + 1):
        if a > 1 and cancelled(job_id):
            log.info("%s остановлено: новых попыток не делаю", trace)
            break
        if a > 1 and not billing.has_funds(ids["project"]):
            say("err", f"💳 {sku} · кадр {pos:02d}: баланс исчерпан — новые попытки не делаю", ids["project"])
            break
        from ..services.payments import retry_context
        retry_context.set(a > 1)
        set_note(job_id, f"попытка {a}/{tries}" if tries > 1 else "генерация")
        ta = time.time()
        gen_prompt = full_prompt(prompt)
        pend = []                 # строки generations со статусом pending: номер задачи Polza сохранён до ожидания

        def on_task(task_id, a=a, gen_prompt=gen_prompt):
            with db.session() as s:
                g = Generation(frame_id=ids["frame"], job_id=job_id, attempt=a, model=st["model"], prompt=gen_prompt,
                               status="pending", external_id=task_id, billing_operation_id=payments.operation_context.get(), instruction=edit, source_id=source_gen)
                s.add(g)
                s.flush()
                pend.append(g.id)
        try:
            data = polza.generate(st, key, gen_prompt, refs + persona_refs + style_refs, str(trace), on_task=on_task)
            try:
                img = polza.extract_image(data)
            except Exception as e:      # оплачено, но не скачалось — заберём позже
                raise polza.Pending(str(e), pend[-1] if pend else "") from e
            if not img:
                raise RuntimeError("в ответе Polza нет картинки")
        except polza.Pending as e:
            error = e
            log.warning("%s %s", trace, e)
            say("info", f"⏳ {sku} · кадр {pos:02d}: {e}", ids["project"])
            with db.session() as s:        # все, кроме последней, — неудавшиеся попытки внутри одного запроса
                for gid in pend[:-1]:
                    s.get(Generation, gid).status = "error"
            break
        except Exception as e:
            error = e
            with db.session() as s:
                for gid in pend:
                    g = s.get(Generation, gid)
                    g.status, g.error, g.seconds = "error", str(e)[:2000], time.time() - ta
                if not pend:
                    s.add(Generation(frame_id=ids["frame"], job_id=job_id, attempt=a, model=st["model"], prompt=gen_prompt,
                                     status="error", error=str(e)[:2000], seconds=time.time() - ta, instruction=edit,
                                     source_id=source_gen))
            break
        cost = polza.cost_of(data)
        provider = data.get("provider", "")
        total += cost
        trace.add("edit" if edit else "generation", st["model"], cost, provider=provider, operation_id=data.get("_billing_operation"))
        with db.session() as s:   # оплаченный результат — сразу в базу и хранилище
            asset = storage.put(s, ids["org"], img, "output", f"{sku}_{pos:02d}_a{a}{'_edit' if edit else ''}.png")
            for gid in pend[:-1]:
                s.get(Generation, gid).status = "error"
            g = s.get(Generation, pend[-1]) if pend else None
            if g is None:
                g = Generation(frame_id=ids["frame"], job_id=job_id, attempt=a, model=st["model"], prompt=gen_prompt,
                               instruction=edit, source_id=source_gen)
                s.add(g)
            g.provider, g.status, g.output_asset_id, g.cost_rub = provider, "ok", asset.id, cost
            g.seconds, g.external_id = time.time() - ta, str(data.get("id") or g.external_id or "")
            s.flush()
            write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"generation:{g.id}")
            gen_id = g.id
        att = {"gen": gen_id, "img": img, "qc": None, "n": a, "provider": provider}
        attempts.append(att)
        if not qc_on:
            break
        set_note(job_id, f"проверка {a}/{tries}" if tries > 1 else "проверка")
        try:
            res = qc.run_qc(st, base_prompt, check_refs, img, trace)
        except Exception as e:
            log.debug("%s трассировка проверки\n%s", trace, traceback.format_exc())
            say("err", f"⚠️ {sku} · кадр {pos:02d}: проверка не выполнена — {str(e)[:200]}. Кадр сохранён без проверки",
                ids["project"])
            with db.session() as s:
                write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"generation:{gen_id}")
            break
        att["qc"] = res
        total += res["cost"]
        with db.session() as s:
            s.add(QCCheck(frame_id=ids["frame"], generation_id=gen_id, model=st.get("qc_model", ""), passed=res["pass"],
                          reasons=[x for x in res["defects"].split("; ") if x], tech=res["tech"], counts=res["counts"],
                          info=res["info"], cost_rub=res["cost"], source="gen"))
            write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"generation:{gen_id}")
        if res["pass"]:
            break
        say("info", f"🔍 {sku} · кадр {pos:02d} · попытка {a}: брак — {res['defects'][:160]}", ids["project"])
        prompt = qc.correction(first_prompt, res["fix"] or res["defects"])

    if not attempts:
        if isinstance(error, polza.Pending):
            return      # задача Polza принята; кадр показывает «ждём результат», картинку заберёт workers/resume.py
        raise error or RuntimeError("генерация остановлена")
    best = _best(attempts)
    with db.session() as s:
        for x in attempts:
            s.get(Generation, x["gen"]).outcome = "current" if x is best else "rejected"
        if prev_gen and prev_gen != best["gen"]:
            g = s.get(Generation, prev_gen)
            if g and g.outcome == "current":
                g.outcome = "archived"
        f = s.get(Frame, ids["frame"])
        f.current_generation_id = best["gen"]
        f.status = frame_status(best["qc"])
    _report(sku, pos, ids["project"], qc_on, best, attempts, total, time.time() - t0, error, edit)


def _best(attempts):
    """Первая прошедшая проверку попытка; иначе — с наименьшим числом дефектов; иначе — последняя."""
    passed = [x for x in attempts if x["qc"] and x["qc"]["pass"]]
    if passed:
        return passed[0]
    checked = [x for x in attempts if x["qc"]]
    if checked and len(checked) == len(attempts):
        return max(checked, key=lambda x: x["qc"]["min"])
    return attempts[-1]


def _report(sku, pos, project_id, qc_on, best, attempts, total, secs, error, edit=""):
    tail = f"{total:.2f} ₽ · {secs:.0f} с · {best['provider'] or '—'}"
    if edit:
        sku = f"✏ {sku}"
    q = best["qc"]
    if not qc_on:
        say("ok", f"✅ {sku} · кадр {pos:02d} · {tail}", project_id)
    elif q is None:
        say("info", f"⬜ {sku} · кадр {pos:02d} · без проверки · {tail}", project_id)
    elif q["pass"]:
        extra = f" с {best['n']}-й попытки" if best["n"] > 1 else ""
        say("ok", f"✅ {sku} · кадр {pos:02d} · проверку прошёл{extra} · {tail}", project_id)
    else:
        say("err", f"⚠️ {sku} · кадр {pos:02d} · брак после {len(attempts)} попыток → ручная проверка · {tail}", project_id)
    if error:
        say("err", f"❌ {sku} · кадр {pos:02d} · попытка {len(attempts) + 1} не удалась: {str(error)[:200]}", project_id)

