import { DocumentLink } from "../../desktop/DocumentLink";
import { useEffect, useRef, useState } from "react";
import { assetUrl } from "../../api/client";
import type { Persona, PersonaGroupTree, PersonaPhoto, PersonaStyle } from "../../api/types";
import { PersonaGroups } from "./PersonaGroups";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { useProject } from "../../ProjectContext";
import { Icon } from "../../layout/Icon";

const KIND_RU: Record<string, string> = { main: "основное", photo: "фото", sheet: "ракурс", candidate: "вариант", ref: "референс" };
const VIEW_RU: Record<string, string> = { portrait: "портрет", "three-quarter": "¾", side: "профиль", "full front": "в рост" };
const STYLE_FIELDS: [keyof PersonaStyle, string, string][] = [
  ["makeup", "Макияж", "dark plum lipstick, smoky black eyeliner, pale matte skin"],
  ["hair_styling", "Укладка", "long straight black hair with a heavy blunt fringe"],
  ["clothing_style", "Стиль одежды", "black lace, velvet and leather, corsets, long skirts, platform boots"],
  ["accessories", "Аксессуары", "silver rings and chokers, black nail polish"],
  ["vibe", "Настроение образа", "romantic gothic, mysterious"],
  ["expression", "Выражение и подача", "calm intense gaze, poised elegant posing"],
];
const EDIT_EXAMPLES = ["рыжие волосы", "короткая стрижка каре", "макияж ярче", "добавить пирсинг в нос", "моложе на 5 лет", "загар"];

type Panel = null | "more" | "edit";

export function PersonaCard({ persona: p, onChange, groups, conflicts }: {
  persona: Persona; onChange: () => Promise<void>; groups: PersonaGroupTree[]; conflicts: Record<string, string[]>;
}) {
  const { api, run, state } = useProject();
  const ui = useUI();
  const [name, setName] = useState(p.name);
  const [desc, setDesc] = useState(p.description);
  const [style, setStyle] = useState<PersonaStyle>(p.style || {});
  const [panel, setPanel] = useState<Panel>(null);
  const [brief, setBrief] = useState(p.brief);
  const [request, setRequest] = useState("");
  const [count, setCount] = useState(2);
  const input = useRef<HTMLInputElement>(null);
  const running = p.job?.state === "running";
  const candidates = p.photos.filter((x) => x.kind === "candidate");
  const kept = p.photos.filter((x) => x.kind !== "candidate" && x.kind !== "ref");
  const refs = p.photos.filter((x) => x.kind === "ref");
  const refInput = useRef<HTMLInputElement>(null);
  const hasMain = p.photos.some((x) => x.kind === "main");
  const hasSheet = p.photos.some((x) => x.kind === "sheet");
  const avg = state.totals.avg_cost;
  const price = (n: number) => (avg ? ` (≈ ${rub(n * avg)})` : "");
  const styleChanged = JSON.stringify(style) !== JSON.stringify(p.style || {}) || desc !== p.description;

  useEffect(() => setDesc(p.description), [p.description]);
  useEffect(() => setStyle(p.style || {}), [p.style]);
  useEffect(() => setName(p.name), [p.name]);
  useEffect(() => setBrief(p.brief), [p.brief]);

  const act = (fn: () => Promise<unknown>, msg?: string) =>
    run(async () => {
      await fn();
      if (msg) ui.toast(msg);
      await onChange();
    });

  const choose = (ph: PersonaPhoto) =>
    act(async () => {
      if (hasMain && !(await ui.confirm({ text: "Сделать этот вариант основным образом? Прежний образ и его ракурсы будут убраны.", ok: "Выбрать" }))) return;
      await api.choosePersonaPhoto(p.id, ph.id);
    }, "Основной образ выбран — его паспорт будет задавать стиль на кадрах товара");

  const more = () =>
    act(async () => {
      await api.personaCandidates(p.id, count, brief);
      setPanel(null);
    }, `Генерирую вариантов: ${count}`);

  const edit = () =>
    act(async () => {
      if (!request.trim()) {
        ui.toast("Напишите, что изменить");
        return;
      }
      await api.editPersona(p.id, request.trim(), count);
      setPanel(null);
      setRequest("");
    }, `Меняю внешность — вариантов: ${count}`);

  const sheet = () =>
    act(async () => {
      const ok = await ui.confirm({
        title: "Дополнительные ракурсы",
        text: `3 генерации${price(3)}: портрет, ¾ и профиль того же человека. С ними генератор точнее держит лицо и фигуру на кадрах товара.`,
        ok: "Сделать",
      });
      if (ok) await api.personaSheet(p.id);
    });

  const remove = () =>
    act(async () => {
      const ok = await ui.confirm({ text: `Убрать модель «${p.name}» в архив? В товарах и проектах она перестанет использоваться.`, ok: "В архив" });
      if (ok) await api.archivePersona(p.id);
    });

  const upload = (files: FileList | null) =>
    act(async () => {
      if (!p.consent) {
        const ok = await ui.confirm({ text: <>У вас есть согласие этого человека на использование его фото для изображений товаров?{" "}
          <DocumentLink kind="persona_photo">Подробнее</DocumentLink>. Отметка сохранится в журнале согласий.</>, ok: "Да, есть" });
        if (!ok) return;
        await api.updatePersona(p.id, { consent: true });
      }
      for (const f of [...(files || [])].slice(0, 4)) await api.uploadPersonaPhoto(p.id, f);
      await api.describePersona(p.id);
    }, "Фото добавлены, ИИ обновляет паспорт образа");

  const addRefs = (files: FileList | null) =>
    act(async () => {
      for (const f of [...(files || [])].slice(0, Math.max(0, 4 - refs.length))) await api.uploadPersonaRef(p.id, f);
    }, "Референсы добавлены — они учтутся в следующих вариантах образа");

  const countSelect = (
    <select value={count} onChange={(e) => setCount(+e.target.value)} title="Сколько вариантов сгенерировать">
      {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n} {n === 1 ? "вариант" : n < 5 ? "варианта" : "вариантов"}</option>)}
    </select>
  );

  const photo = (ph: PersonaPhoto) => (
    <div key={ph.id} className={`pphoto ${ph.kind}`}>
      <img loading="lazy" src={assetUrl(ph.asset, 400)} alt="" title="Открыть крупно"
        onClick={() => { const list = p.photos.filter((x) => x.kind === ph.kind); ui.zoom(list.map((x) => ({ asset: x.asset, caption: `${p.name} · ${KIND_RU[x.kind] || ""}` })), list.indexOf(ph)); }} />
      {ph.kind !== "candidate" && <span className="pk">{KIND_RU[ph.kind]}{ph.view && ph.kind === "sheet" ? ` · ${VIEW_RU[ph.view] || ph.view}` : ""}</span>}
      <button className="pdel" title="Удалить" onClick={() => act(() => api.deletePersonaPhoto(p.id, ph.id))}>✕</button>
      {ph.kind === "candidate" && (
        <>
          {ph.title && <div className="ptitle" title={ph.title}>{ph.title}</div>}
          <button className="primary" onClick={() => choose(ph)}>{hasMain ? "Заменить основной" : "Выбрать"}</button>
        </>
      )}
    </div>
  );

  return (
    <section className={`card persona ${p.is_default ? "default" : ""}`}>
      <div className="card-h">
        <input type="text" className="persona-name" value={name} onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() && name !== p.name && act(() => api.updatePersona(p.id, { name: name.trim() }))} />
        <span className={`tag ${p.status === "ready" ? "" : "bad"}`}>{p.status === "ready" ? "готова" : "не готова"}</span>
        <span className="tag">{p.source === "upload" ? "свои фото" : "сгенерирована"}</span>
        {p.products > 0 && <span className="tag">товаров в проекте: {p.products}</span>}
        {running && <span className="pbusy">{p.job?.note || "в работе"}…</span>}
        <span className="spacer" />
        <label className="check" title="Использовать эту модель для всех товаров проекта (кроме тех, где выбрана другая)">
          <input type="radio" name="persona-default" checked={p.is_default} disabled={p.status !== "ready"}
            onChange={() => act(() => api.setProjectPersona(p.id), `«${p.name}» — модель проекта`)} /> модель проекта
        </label>
        {p.is_default && <button onClick={() => act(() => api.setProjectPersona(0), "Модель клиента в проекте выключена")}>не использовать</button>}
        <button className="danger" onClick={remove}>В архив</button>
      </div>

      {p.job?.state === "error" && <div className="err-text">Ошибка: {p.job.error}</div>}

      {kept.length > 0 && <div className="persona-photos">{kept.map(photo)}</div>}

      {candidates.length > 0 && (
        <>
          <div className="hint mb8">
            {hasMain ? "Новые варианты — выберите, чтобы заменить основной образ (или удалите лишние ✕):" : "Выберите вариант образа — он станет основным:"}
          </div>
          <div className="persona-photos">{candidates.map(photo)}</div>
        </>
      )}

      <div className="row mt10">
        <button disabled={running} className={panel === "more" ? "on" : ""} onClick={() => setPanel(panel === "more" ? null : "more")}>＋ Ещё варианты…</button>
        {hasMain && <button disabled={running} className={panel === "edit" ? "on" : ""} onClick={() => setPanel(panel === "edit" ? null : "edit")}>Изменить внешность…</button>}
        {hasMain && <button disabled={running} onClick={sheet}>{hasSheet ? "↻ Переделать ракурсы" : "Сделать ракурсы (портрет, ¾, профиль)"}</button>}
        <button disabled={running} onClick={() => input.current?.click()}>Добавить фото</button>
        {hasMain && p.source === "upload" && <button disabled={running} onClick={() => act(() => api.describePersona(p.id), "ИИ описывает внешность и стиль…")}>Описать по фото</button>}
        <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
      </div>

      {panel === "more" && (
        <div className="persona-panel">
          <div className="hint">Новые варианты по пожеланиям — можно уточнить их перед генерацией:</div>
          <textarea className="short" value={brief} placeholder="пол, возраст, внешность, стиль" onChange={(e) => setBrief(e.target.value)} />
          <div className="persona-refs">
            <b>Референсы образа</b>
            <span className="hint">причёска, макияж, одежда, настроение — лицо не копируется{refs.length ? ` · ${refs.length} из 4` : ""}</span>
            <div className="persona-photos small">
              {refs.map(photo)}
              {refs.length < 4 && <button className="ref-add" onClick={() => refInput.current?.click()}><Icon name="plus" size={18} />фото</button>}
            </div>
            <input ref={refInput} type="file" accept="image/*" multiple hidden onChange={(e) => { addRefs(e.target.files); e.target.value = ""; }} />
          </div>
          <div className="row">{countSelect}<span className="hint">каждый вариант — одна генерация{price(1)}</span>
            <span className="spacer" /><button onClick={() => setPanel(null)}>Отмена</button>
            <button className="primary" disabled={!brief.trim()} onClick={more}>Сгенерировать {count}{price(count)}</button></div>
        </div>
      )}

      {panel === "edit" && (
        <div className="persona-panel">
          <div className="hint">Что изменить у выбранной модели? Остальное — лицо, фигура, стиль — останется прежним.</div>
          <input type="text" className="grow wide" autoFocus value={request} placeholder="например: рыжие волосы до плеч, макияж ярче"
            onChange={(e) => setRequest(e.target.value)} onKeyDown={(e) => e.key === "Enter" && edit()} />
          <div className="row">{EDIT_EXAMPLES.map((x) => (
            <button key={x} className="pchip" onClick={() => setRequest(request ? `${request}, ${x}` : x)}>{x}</button>))}</div>
          <div className="row">{countSelect}<span className="hint">основной образ заменится только когда вы выберете вариант</span>
            <span className="spacer" /><button onClick={() => setPanel(null)}>Отмена</button>
            <button className="primary" onClick={edit}>Изменить · {count}{price(count)}</button></div>
        </div>
      )}

      <div className="persona-groups mt10">
        <div className="row nowrap">
          <b>Для каких товаров</b>
          <span className="hint">
            {p.usage.total ? `снимает товаров в проекте: ${p.usage.total}` +
              ` (по группам ${p.usage.groups}, выбрана вручную ${p.usage.own}, как модель проекта ${p.usage.project})` : "в проекте пока ни одного товара"}
          </span>
        </div>
        <div className="hint mb8">Отмеченные категории и подразделы снимаются на этой модели, в том числе новые товары после импорта.
          Подраздел точнее категории; модель, выбранная в профиле товара, главнее всего. Остальные товары — на модели проекта.</div>
        <PersonaGroups tree={groups} value={p.groups} conflicts={conflicts} ownName={p.name}
          onChange={(g) => act(() => api.updatePersona(p.id, { groups: g }), "Группы модели сохранены")} />
        {p.status !== "ready" && p.groups.length > 0 && <div className="err-text">Модель ещё не готова — группы начнут работать, когда будет выбран образ.</div>}
      </div>

      {state.admin && <details className="persona-passport mt10 admin-only">
        <summary>Паспорт образа — то, что получает генератор (видно только мастер-аккаунту){p.style?.vibe ? ` · ${p.style.vibe}` : ""}</summary>
        <div className="hint mb8">
          Составляется ИИ для каждого варианта и сохраняется у выбранного. Внешность держится на всех кадрах товара; макияж,
          укладка и аксессуары сохраняются; стиль одежды задаёт, во что одевать модель под товар.
        </div>
        <div className="form grid">
          <label className="form-label">Внешность</label>
          <textarea className="short" value={desc} placeholder={running ? "ИИ составляет…" : "появится после выбора варианта или анализа фото"}
            onChange={(e) => setDesc(e.target.value)} />
          {STYLE_FIELDS.map(([k, label, ph]) => (
            <Field key={k} label={label} value={style[k] || ""} placeholder={ph} onChange={(v) => setStyle({ ...style, [k]: v })} />
          ))}
        </div>
        {p.brief && <div className="hint mt6">Пожелания клиента: {p.brief}</div>}
        {styleChanged && (
          <div className="row">
            <span className="spacer" />
            <button onClick={() => { setDesc(p.description); setStyle(p.style || {}); }}>Отменить правки</button>
            <button className="primary" onClick={() => act(() => api.updatePersona(p.id, { description: desc, style }), "Паспорт образа сохранён")}>Сохранить паспорт</button>
          </div>
        )}
      </details>}
    </section>
  );
}

function Field({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (v: string) => void }) {
  return (
    <>
      <label className="form-label">{label}</label>
      <input type="text" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </>
  );
}
