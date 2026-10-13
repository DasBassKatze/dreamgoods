import { useCallback, useEffect, useRef, useState } from "react";
import { assetUrl } from "../../api/client";
import type { StyleListing, StyleRef } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";

const NOTE_EXAMPLES = ["нравится тёплый вечерний свет", "бежевая и молочная гамма", "минимализм, много воздуха",
  "фон не брать, только свет и цвет", "контрастный студийный свет", "плёночная обработка"];

/** Референсы оформления: фото-пример стиля + что в нём нравится. Общие для всех проектов клиента. */
export function StyleManager({ onClose }: { onClose: () => void }) {
  const { api, state, reload, run } = useProject();
  const ui = useUI();
  const [data, setData] = useState<StyleListing | null>(null);
  const [creating, setCreating] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const r = await api.styles();
      setData(r);
      return r;
    } catch (e) {
      ui.toast((e as Error).message);
      return null;
    }
  }, [api, ui]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await load();
      if (!alive) return;
      timer.current = window.setTimeout(tick, r?.refs.some((x) => x.job?.state === "running") ? 2000 : 8000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer.current); };
  }, [load]);

  const refresh = async () => { await load(); await reload(); };

  return (
    <Modal title={<>🎨 Референсы оформления <span className="hint">· {state.project.client}</span></>} width={1100} onClose={onClose}
      actions={!creating && <button className="primary" onClick={() => setCreating(true)}>＋ Новый референс</button>}>
      <div className="hint mb10">
        Фото-пример того, как должны выглядеть кадры: свет, цвет, фон и обстановка, композиция, настроение. ИИ разбирает стиль,
        а генератор получает фото как пример оформления — без копирования предметов, людей и текста. Обложку карточки референс
        не меняет: там правила площадки.
      </div>
      {creating && data && <NewStyle blocks={data.blocks} onCancel={() => setCreating(false)}
        onCreated={async () => { setCreating(false); await refresh(); }} />}
      {!data ? <div className="empty">Загрузка…</div> : !data.refs.length && !creating ? (
        <div className="empty">Референсов пока нет.
          <div className="row center"><button className="primary" onClick={() => setCreating(true)}>＋ Новый референс</button></div></div>
      ) : data.refs.map((r) => <StyleCard key={r.id} r={r} blocks={data.blocks} onChange={refresh} run={run} />)}
    </Modal>
  );
}

function NewStyle({ blocks, onCancel, onCreated }: { blocks: StyleListing["blocks"]; onCancel: () => void; onCreated: () => void }) {
  const { api, run } = useProject();
  const ui = useUI();
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sel, setSel] = useState<string[]>(["detail", "usage", "scene", "lifestyle"]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const submit = () =>
    run(async () => {
      if (!files.length) { ui.toast("Выберите фото-пример"); return; }
      setBusy(true);
      const r = await api.createStyle({ name: name.trim(), note: note.trim(), blocks: sel });
      for (const f of files) await api.uploadStylePhoto(r.id, f);
      await api.describeStyle(r.id);
      ui.toast("ИИ разбирает стиль…");
      onCreated();
    }).finally(() => setBusy(false));

  return (
    <div className="persona-new">
      <div className="form grid">
        <label className="form-label">Фото-пример</label>
        <div className="row nowrap">
          <button onClick={() => input.current?.click()}>Выбрать фото…</button>
          <span className="hint">{files.length ? `выбрано: ${files.length}` : "1–3 фото: съёмки, которые нравятся (свои, конкурентов, из подборок)"}</span>
          <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => setFiles([...(e.target.files || [])].slice(0, 3))} />
        </div>
        {files.length > 0 && <><span />
          <div className="persona-photos">{files.map((f) => <div key={f.name} className="pphoto"><img src={URL.createObjectURL(f)} alt="" /></div>)}</div></>}
        <label className="form-label">Что взять из примера</label>
        <div>
          <textarea className="short" value={note} placeholder="коротко: свет, цвет, фон, настроение — и что НЕ брать"
            onChange={(e) => setNote(e.target.value)} />
          <div className="row">{NOTE_EXAMPLES.map((x) => (
            <button key={x} className="pchip" onClick={() => setNote(note ? `${note}, ${x}` : x)}>{x}</button>))}</div>
        </div>
        <label className="form-label">Название</label>
        <input type="text" value={name} placeholder="необязательно — ИИ придумает" onChange={(e) => setName(e.target.value)} />
        <label className="form-label">К каким кадрам</label>
        <Blocks blocks={blocks} value={sel} onChange={setSel} />
      </div>
      <div className="row mt12"><span className="spacer" /><button onClick={onCancel}>Отмена</button>
        <button className="primary" disabled={busy} onClick={submit}>Загрузить и разобрать стиль</button></div>
    </div>
  );
}

function Blocks({ blocks, value, onChange }: { blocks: StyleListing["blocks"]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="row">
      {blocks.map((b) => (
        <label key={b.key} className={`pchip ${value.includes(b.key) ? "cur" : ""}`}>
          <input type="checkbox" checked={value.includes(b.key)}
            onChange={(e) => onChange(e.target.checked ? [...value, b.key] : value.filter((x) => x !== b.key))} /> {b.name}
        </label>
      ))}
    </div>
  );
}

function StyleCard({ r, blocks, onChange, run }: { r: StyleRef; blocks: StyleListing["blocks"]; onChange: () => Promise<void>;
  run: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { api } = useProject();
  const ui = useUI();
  const [name, setName] = useState(r.name);
  const [note, setNote] = useState(r.note);
  const [desc, setDesc] = useState(r.description);
  const input = useRef<HTMLInputElement>(null);
  const running = r.job?.state === "running";
  useEffect(() => { setName(r.name); setNote(r.note); setDesc(r.description); }, [r.name, r.note, r.description]);
  const act = (fn: () => Promise<unknown>, msg?: string) => run(async () => { await fn(); if (msg) ui.toast(msg); await onChange(); });
  const dirty = note !== r.note || desc !== r.description;

  return (
    <section className={`card persona ${r.is_default ? "default" : ""}`}>
      <div className="card-h">
        <input type="text" className="persona-name" value={name} onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() && name !== r.name && act(() => api.updateStyle(r.id, { name: name.trim() }))} />
        <span className={`tag ${r.status === "ready" ? "" : "bad"}`}>{r.status === "ready" ? "готов" : "не готов"}</span>
        {r.products > 0 && <span className="tag">товаров в проекте: {r.products}</span>}
        {running && <span className="pbusy">разбираю стиль…</span>}
        <span className="spacer" />
        <label className="check"><input type="radio" name="style-default" checked={r.is_default} disabled={r.status !== "ready"}
          onChange={() => act(() => api.setProjectStyle(r.id))} /> оформление проекта</label>
        {r.is_default && <button onClick={() => act(() => api.setProjectStyle(0))}>не использовать</button>}
        <button className="danger" onClick={() => act(async () => {
          if (await ui.confirm({ text: `Убрать «${r.name}» в архив?`, ok: "В архив" })) await api.archiveStyle(r.id);
        })}>В архив</button>
      </div>
      {r.job?.state === "error" && <div className="err-text">Ошибка: {r.job.error}</div>}
      <div className="persona-photos">
        {r.photos.map((ph) => (
          <div key={ph.id} className="pphoto">
            <img loading="lazy" src={assetUrl(ph.asset, 400)} alt="" onClick={() => window.open(assetUrl(ph.asset), "_blank")} />
            <button className="pdel" title="Удалить" onClick={() => act(() => api.deleteStylePhoto(r.id, ph.id))}>✕</button>
          </div>
        ))}
        {r.photos.length < 3 && <button className="pphoto add" onClick={() => input.current?.click()}>＋ фото</button>}
        <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => {
          const fs = [...(e.target.files || [])]; e.target.value = "";
          act(async () => { for (const f of fs.slice(0, 3 - r.photos.length)) await api.uploadStylePhoto(r.id, f); await api.describeStyle(r.id); },
            "Фото добавлены, ИИ обновляет разбор стиля");
        }} />
      </div>
      <div className="form grid">
        <label className="form-label">Что взять из примера</label>
        <textarea className="short" value={note} onChange={(e) => setNote(e.target.value)} />
        <label className="form-label">Применять к кадрам</label>
        <Blocks blocks={blocks} value={r.blocks} onChange={(v) => act(() => api.updateStyle(r.id, { blocks: v }))} />
      </div>
      <details className="persona-passport mt10">
        <summary>Разбор стиля — то, что получает генератор</summary>
        <textarea className="short" value={desc} placeholder={running ? "ИИ разбирает…" : "появится после разбора"} onChange={(e) => setDesc(e.target.value)} />
      </details>
      <div className="row">
        <button disabled={running || !r.photos.length} onClick={() => act(async () => {
          if (note !== r.note) await api.updateStyle(r.id, { note });
          await api.describeStyle(r.id);
        }, "ИИ заново разбирает стиль…")}>🧠 Разобрать заново</button>
        <span className="spacer" />
        {dirty && <button className="primary" onClick={() => act(() => api.updateStyle(r.id, { note, description: desc }), "Сохранено")}>Сохранить</button>}
      </div>
    </section>
  );
}
