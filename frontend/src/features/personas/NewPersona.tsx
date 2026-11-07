import { DocumentLink } from "../../desktop/DocumentLink";
import { useRef, useState } from "react";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { useProject } from "../../ProjectContext";

type Mode = "generated" | "upload";

const EXAMPLES = [
  "девушка 25 лет, славянская внешность, длинные русые волосы, стройная, естественный макияж",
  "женщина 40 лет, ухоженная, каре, элегантный стиль",
  "мужчина 35 лет, спортивный, короткая стрижка, лёгкая щетина",
  "готическая внешность: бледная кожа, чёрные длинные волосы, тёмная помада, пирсинг",
];

export function NewPersona({ onCancel, onCreated }: { onCancel: () => void; onCreated: () => void }) {
  const { api, state, run } = useProject();
  const ui = useUI();
  const [mode, setMode] = useState<Mode>("generated");
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [count, setCount] = useState(3);
  const [consent, setConsent] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [refs, setRefs] = useState<File[]>([]);
  const refInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const avg = state.totals.avg_cost;

  const submit = () =>
    run(async () => {
      if (mode === "generated") {
        if (!brief.trim()) {
          ui.toast("Опишите, какой должна быть модель");
          return;
        }
        const ok = await ui.confirm({
          title: "Сгенерировать варианты образа",
          text: `Будет ${count} генерации(й)${avg ? ` — примерно ${rub(count * avg)}` : ""}. Потом выберете один вариант.`,
          ok: "Сгенерировать",
        });
        if (!ok) return;
        setBusy(true);
        const r = await api.createPersona({ name: name.trim(), brief: brief.trim(), source: "generated" });
        for (const f of refs) await api.uploadPersonaRef(r.id, f);
        await api.personaCandidates(r.id, count);
      } else {
        if (!files.length) {
          ui.toast("Выберите фото модели");
          return;
        }
        if (!consent) {
          ui.toast("Подтвердите согласие человека на использование фото");
          return;
        }
        setBusy(true);
        const r = await api.createPersona({ name: name.trim() || "Модель", source: "upload" });
        await api.updatePersona(r.id, { consent: true });
        for (const f of files) await api.uploadPersonaPhoto(r.id, f);
        await api.describePersona(r.id);
      }
      ui.toast(mode === "generated" ? "Генерирую варианты образа…" : "Фото загружены, ИИ описывает внешность…");
      onCreated();
    }).finally(() => setBusy(false));

  return (
    <div className="persona-new">
      <div className="seg mb10">
        <button className={mode === "generated" ? "on" : ""} onClick={() => setMode("generated")}>Сгенерировать образ</button>
        <button className={mode === "upload" ? "on" : ""} onClick={() => setMode("upload")}>Загрузить фото своей модели</button>
      </div>
      <div className="form grid">
        <label className="form-label">Название</label>
        <input type="text" value={name} placeholder={mode === "generated" ? "необязательно — ИИ придумает" : "например, Анна"}
          onChange={(e) => setName(e.target.value)} />
        {mode === "generated" ? (
          <>
            <label className="form-label">Какой должна быть модель</label>
            <div>
              <textarea className="short" value={brief} placeholder="пол, возраст, внешность, телосложение, стиль"
                onChange={(e) => setBrief(e.target.value)} />
              <div className="row">
                {EXAMPLES.map((x) => <button key={x} className="pchip" onClick={() => setBrief(x)}>{x.split(",")[0]}…</button>)}
              </div>
              <div className="hint mt6">Можно описать и стиль: готика, стритвир, old money, макияж, татуировки, украшения. ИИ составит
                для каждого варианта подробный «паспорт образа» — внешность и стиль. Паспорт выбранного варианта потом задаёт
                макияж, укладку и стиль одежды на кадрах товара.</div>
            </div>
            <label className="form-label">Референсы образа</label>
            <div>
              <div className="row nowrap">
                <button onClick={() => refInput.current?.click()}>{refs.length ? "Заменить фото…" : "Добавить фото…"}</button>
                <span className="hint">{refs.length ? `выбрано: ${refs.length}` : "необязательно, до 4 фото"}</span>
                {refs.length > 0 && <button className="link" onClick={() => setRefs([])}>убрать</button>}
              </div>
              {refs.length > 0 && (
                <div className="ref-previews">{refs.map((f) => <img key={f.name + f.size} src={URL.createObjectURL(f)} alt="" />)}</div>
              )}
              <div className="hint mt6">Фото-примеры образа: причёска, макияж, одежда, настроение. В пожеланиях можно уточнить, что взять
                («причёску и макияж как на фото»). Лицо с референса не копируется — модель будет новым человеком. Снимать
                конкретного человека — «Загрузить фото своей модели».</div>
              <input ref={refInput} type="file" accept="image/*" multiple hidden
                onChange={(e) => { setRefs([...(e.target.files || [])].slice(0, 4)); e.target.value = ""; }} />
            </div>
            <label className="form-label">Вариантов</label>
            <div className="row nowrap">
              <select value={count} onChange={(e) => setCount(+e.target.value)}>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <span className="hint">каждый вариант — одна генерация{avg ? ` (≈ ${rub(avg)})` : ""}</span>
            </div>
          </>
        ) : (
          <>
            <label className="form-label">Фото</label>
            <div>
              <div className="row nowrap">
                <button onClick={() => input.current?.click()}>Выбрать фото…</button>
                <span className="hint">{files.length ? `выбрано: ${files.length}` : "1–4 фото: лицо крупно и в полный рост, хороший свет"}</span>
              </div>
              <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => setFiles([...(e.target.files || [])].slice(0, 4))} />
            </div>
            <label className="form-label">Согласие</label>
            <label className="check">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> у меня есть согласие этого
              человека на использование его фото для создания изображений товаров — <DocumentLink kind="persona_photo">что это значит</DocumentLink>. Отметка сохраняется в журнале согласий
            </label>
          </>
        )}
      </div>
      <div className="row mt12">
        <span className="spacer" />
        <button onClick={onCancel}>Отмена</button>
        <button className="primary" disabled={busy} onClick={submit}>
          {mode === "generated" ? "Сгенерировать варианты" : "Загрузить"}
        </button>
      </div>
    </div>
  );
}
