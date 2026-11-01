"""Задание «generate»: генерация кадра → ИИ-проверка → автоперегенерация брака с описанием дефектов."""
import time
import traceback

from sqlalchemy import select

from .. import db
from ..ai import persona as personas
from ..ai import prompts as P
from ..ai import styleref
from ..ai import polza, qc, series
from ..ai.images import PostSlot, fit_side, ref_for
from ..core import presets as presets_core
from ..core import storage
from ..core.events import say
from ..core.logs import Trace, log
from ..db.models import Frame, Generation, Job, Product, QCCheck
from ..services import billing, moderation
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
        run = job.payload or {}
        # пожелания: к запуску (если переданы) или из пресета (режим «Авто»)
        brief = (run.get("brief") or "").strip() or (st.get("preset_brief") or "").strip()
        if run.get("market"):                               # площадка запуска поверх пресета
            rules = presets_core.market_rules({"key": run["market"], "cover": True})
            st = dict(st, market=rules)
            if rules.get("aspect"):
                st["aspect"] = rules["aspect"]
            if rules.get("min_side"):
                st["qc_min_side"] = rules["min_side"]
        if run.get("aspect"):
            st = dict(st, aspect=run["aspect"])
        if run.get("resolution"):                           # «Улучшить до 4K»
            st = dict(st, resolution=run["resolution"], out_side=3600)
        comment = (job.payload or {}).get("comment", "")
        edit = ((job.payload or {}).get("edit") or "").strip()     # правка готового фото по промпту
        edit_label = (job.payload or {}).get("label") or ""
        source_gen, source_asset = None, None
        if edit:
            source_gen = int((job.payload or {}).get("source") or prev_gen or 0)
            sg = s.get(Generation, source_gen) if source_gen else None
            if not sg or sg.frame_id != frame.id or not sg.output_asset_id:
                raise RuntimeError("нет исходной картинки для правки — сначала сгенерируйте кадр")
            source_asset = sg.output_asset
            if source_asset.width and source_asset.height:   # правка сохраняет формат исходной версии
                st = dict(st, aspect=polza.nearest_aspect(f"{source_asset.width}:{source_asset.height}", presets_core.ASPECTS))
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
        emotion, anchor_id = "", None
        if not edit and st.get("series", True):     # серия товара как одна фотосессия (ai/series.py)
            mates = s.scalars(select(Frame).where(Frame.product_id == product.id, Frame.status != "retired")
                              .order_by(Frame.position)).all()
            group = series.group_of(base_prompt)
            same = [f for f in mates if series.group_of(f.prompt) == group]
            if same and same[0].id != frame.id:
                anchor_id = same[0].id
            if series.is_full_body(base_prompt):
                full = [f.id for f in mates if series.is_full_body(f.prompt)]
                emotion = series.emotion_for(sku, full.index(frame.id) if frame.id in full else 0)
    trace = Trace(f"[{sku} #{pos:02d}]")
    side = int(st.get("ref_side") or 1536)
    refs = [ref_for(a, side) for a in ref_assets]
    persona_refs = [ref_for(a, side) for a in persona_assets]
    if persona_refs:
        log.info("%s модель клиента «%s»: фото %d", trace, persona_name, len(persona_refs))
    style_refs = [ref_for(a, side) for a in style_assets]
    if style_refs:
        log.info("%s оформление «%s»: фото %d", trace, style_name, len(style_refs))
    anchor_refs = []
    if anchor_id:
        asset = _wait_anchor(anchor_id, job_id, trace)
        if asset is not None:
            anchor_refs = [ref_for(asset, side)]
            log.info("%s серия: опорный кадр — тот же свет, цвет и образ, что на нём", trace)
    if emotion:
        log.info("%s эмоция модели в кадре: %s", trace, emotion)
    if edit:   # фото 1 — текущая версия кадра в полном размере, дальше — фото товара
        refs = [ref_for(source_asset, max(side, 2048))] + refs
        log.info("%s ✏ правка версии #%s: %s", trace, source_gen, edit)

    def full_prompt(p):
        if edit:
            return p
        p = styleref.apply(p, len(refs), len(persona_refs), len(style_refs), style_desc, style_note)
        p = personas.apply(p, persona_desc, len(refs), len(persona_refs), persona_style)
        if brief:
            p += f"\n\nCLIENT WISHES for this photo set (may be in Russian; follow them unless they contradict keeping the product identical): {brief}"
        m = st.get("market") or {}
        if run.get("market") and "main marketplace cover" in base_prompt.lower():
            p += (f"\n\nThis cover must follow the rules of {m.get('name')}: {m.get('cover_bg')}, the product filling "
                  f"{m.get('cover_fill')}" + (f", {m.get('cover_extra')}" if m.get("cover_extra") else "") + ".")
        if not st.get("series", True):
            return series.orient(p, st.get("aspect"))
        n_anchor = len(refs) + len(persona_refs) + len(style_refs) + 1 if anchor_refs else 0
        return series.apply(p, st.get("aspect"), emotion, n_anchor)
    qc_on = bool(st.get("qc_enabled"))
    check_refs = qc_refs(ids["product"], st, ids, trace) if qc_on else []
    regen = qc_on and bool(st.get("qc_autoregen", True))
    tries = 1 if run.get("trial_only") else 1 + (max(0, int(st.get("qc_retries") or 0)) if regen else 0)
    log.info("%s модель %s · референсы %d · проверка %s · попыток до %d", trace, st["model"], len(refs),
             "вкл" if qc_on else "выкл", tries)

    first_prompt = P.edit_prompt(edit, len(refs) - 1, personas.has_person(base_prompt)) if edit else base_prompt
    prompt = qc.correction(first_prompt, comment) if comment else first_prompt
    if comment:
        log.info("%s в промпт добавлено ваше замечание: %s", trace, comment)
    attempts, error, t0, total = [], None, time.time(), 0.0
    post = PostSlot()
    try:
        for a in range(1, tries + 1):
            from ..services.payments import retry_context
            retry_context.set(a > 1 or bool(run.get("budget_retry")))
            if a > 1 and cancelled(job_id):
                log.info("%s остановлено: новых попыток не делаю", trace)
                break
            if a > 1 and not billing.has_funds(ids["project"]):
                say("err", f"💳 {sku} · кадр {pos:02d}: баланс исчерпан — новые попытки не делаю", ids["project"])
                break
            set_note(job_id, f"попытка {a}/{tries}" if tries > 1 else "генерация")
            ta = time.time()
            gen_prompt = full_prompt(prompt)
            pend = []                 # строки generations со статусом pending: номер задачи Polza сохранён до ожидания

            def on_task(task_id, a=a, gen_prompt=gen_prompt):
                with db.session() as s:
                    from ..services.payments import operation_context
                    g = Generation(paid_operation_id=operation_context.get(), frame_id=ids["frame"], job_id=job_id, attempt=a, model=st["model"], prompt=gen_prompt,
                                   status="pending", external_id=task_id, instruction=edit_label or edit, source_id=source_gen)
                    s.add(g)
                    s.flush()
                    pend.append(g.id)
            try:
                data = polza.generate(st, key, gen_prompt, refs + persona_refs + style_refs + anchor_refs, str(trace),
                                         on_task=on_task)
                try:
                    post.acquire()          # не больше POST_LIMIT полноразмерных картинок в памяти одновременно
                    img = polza.extract_image(data)
                    data = {k: v for k, v in data.items() if k not in ("data", "output")}   # base64 результата больше не нужен
                except Exception as e:      # оплачено, но не скачалось — заберём позже
                    raise polza.Pending(str(e), pend[-1] if pend else "") from e
                if not img:
                    raise RuntimeError("в ответе Polza нет картинки")
                img = fit_side(img, presets_core.out_side(st), str(trace), int(st.get("qc_min_side") or 0))
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
                                         status="error", error=str(e)[:2000], seconds=time.time() - ta, instruction=edit_label or edit,
                                         source_id=source_gen))
                break
            cost = polza.cost_of(data)
            provider = data.get("provider", "")
            total += cost
            trace.add("edit" if edit else "generation", st["model"], cost, provider=provider, paid_operation=data.get("_paid_operation"))
            with db.session() as s:   # оплаченный результат — сразу в базу и хранилище
                asset = storage.put(s, ids["org"], img, "output", f"{sku}_{pos:02d}_a{a}{'_edit' if edit else ''}.png")
                for gid in pend[:-1]:
                    s.get(Generation, gid).status = "error"
                g = s.get(Generation, pend[-1]) if pend else None
                if g is None:
                    from ..services.payments import operation_context
                    g = Generation(paid_operation_id=data.get("_paid_operation"), frame_id=ids["frame"], job_id=job_id, attempt=a, model=st["model"], prompt=gen_prompt,
                                   instruction=edit_label or edit, source_id=source_gen)
                    s.add(g)
                g.provider, g.status, g.output_asset_id, g.cost_rub = provider, "ok", asset.id, cost
                g.seconds, g.external_id = time.time() - ta, str(data.get("id") or g.external_id or "")
                s.flush()
                write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"generation:{g.id}")
                gen_id = g.id
            att = {"gen": gen_id, "qc": None, "n": a, "provider": provider}   # саму картинку не держим — она уже в хранилище
            prepared = qc.prepare(img, st, str(trace)) if qc_on else None
            img = None
            post.release()
            attempts.append(att)
            if not qc_on:
                break
            set_note(job_id, f"проверка {a}/{tries}" if tries > 1 else "проверка")
            try:
                res = qc.run_qc(st, base_prompt, check_refs, prepared, trace)
            except Exception as e:
                log.debug("%s трассировка проверки\n%s", trace, traceback.format_exc())
                say("err", f"⚠️ {sku} · кадр {pos:02d}: проверка не выполнена — {str(e)[:200]}. Кадр сохранён без проверки",
                    ids["project"])
                with db.session() as s:
                    write_usage(s, ids["org"], ids["project"], ids["product"], ids["frame"], trace, f"generation:{gen_id}")
                    from ..services.payments import BudgetPause
                    if isinstance(e, BudgetPause):
                        current_job=s.get(Job,job_id)
                        current_job.payload={**(current_job.payload or {}),"deferred_budget_check":True,"deferred_retry":a>1}
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
            if res.get("prohibited"):
                # запрещённое содержание: попытку прячем (в истории и галерее её не будет), в журнал модерации
                with db.session() as s:
                    s.get(Generation, gen_id).status = "blocked"
                moderation.record("frame", "готовый кадр", "image", res["prohibited"], "hidden", ids["project"],
                                  ids["product"], ids["frame"])
                say("err", f"⛔ {sku} · кадр {pos:02d} · попытка {a}: запрещённое содержание — кадр скрыт и переснимается",
                    ids["project"])
            else:
                say("info", f"🔍 {sku} · кадр {pos:02d} · попытка {a}: брак — {res['defects'][:160]}", ids["project"])
            prompt = qc.correction(first_prompt, res["fix"] or res["defects"])
    finally:
        post.release()

    if not attempts:
        if isinstance(error, polza.Pending):
            return      # задача Polza принята; кадр показывает «ждём результат», картинку заберёт workers/resume.py
        raise error or RuntimeError("генерация остановлена")
    best = _best(attempts)
    if best is None:            # все попытки — с запрещённым содержанием: кадр не сохраняется
        with db.session() as s:
            for x in attempts:
                s.get(Generation, x["gen"]).outcome = "rejected"
            f = s.get(Frame, ids["frame"])
            if not f.current_generation_id:
                f.status = "missing"
        say("err", f"⛔ {sku} · кадр {pos:02d} · не сохранён: во всех попытках запрещённое содержание. Проверьте фото товара "
                   f"и пожелания · {total:.2f} ₽", ids["project"])
        return
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


ANCHOR_WAIT = 8 * 60


def _wait_anchor(anchor_id, job_id, trace):
    """Картинка опорного кадра серии. Если он сейчас снимается — ждём (поток спит, это дёшево), чтобы весь товар
    снимался «от первого кадра». Если опорного кадра нет и он не в работе — снимаем без него."""
    deadline = time.time() + ANCHOR_WAIT
    noted = False
    while True:
        with db.session() as s:
            f = s.get(Frame, anchor_id)
            if f is None:
                return None
            g = s.get(Generation, f.current_generation_id) if f.current_generation_id else None
            if g and g.output_asset_id and f.status != "rejected":
                return g.output_asset
            busy = s.scalar(select(Job.id).where(Job.frame_id == anchor_id, Job.status.in_(("queued", "running"))))
        if not busy or time.time() > deadline or cancelled(job_id):
            return None
        if not noted:
            set_note(job_id, "ждёт опорный кадр серии")
            log.info("%s серия: жду опорный кадр — он снимается первым", trace)
            noted = True
        time.sleep(5)


def _best(attempts):
    """Первая прошедшая проверку попытка; иначе — с наименьшим числом дефектов; иначе — последняя.
    Попытки с запрещённым содержанием не выбираются никогда (None — если других нет)."""
    attempts = [x for x in attempts if not (x["qc"] and x["qc"].get("prohibited"))]
    if not attempts:
        return None
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

