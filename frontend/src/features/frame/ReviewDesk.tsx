import { useCallback, useEffect, useState, useRef } from "react";
import { assetUrl } from "../../api/client";
import type { FrameVersion, ReviewItem, ReviewListing } from "../../api/types";
import { useProject } from "../../ProjectContext";
import { useUI } from "../../components/ui";
import { CompareImages } from "./CompareImages";

export function ReviewDesk() {
  const { api, reload } = useProject();
  const ui = useUI();
  const [page, setPage] = useState(1), [status, setStatus] = useState("review"), [defect, setDefect] = useState("");
  const [query, setQuery] = useState(""), [d, setD] = useState<ReviewListing | null>(null);
  const [focus, setFocus] = useState<number | null>(null), [selected, setSelected] = useState<Record<number, ReviewItem>>({});
  const [comment, setComment] = useState(""), [busy, setBusy] = useState(false);
  const [versions, setVersions] = useState<FrameVersion[]>([]), [compare, setCompare] = useState("");
  const [refIndex, setRefIndex] = useState(0), [error, setError] = useState("");
  const requestSeq = useRef(0);
  const load = useCallback(async () => {
    const request = ++requestSeq.current;
    const data = await api.reviews({ page, status, defect, query });
    if (request !== requestSeq.current) return;
    setD(data); setFocus((id) => data.items.some((x) => x.id === id) ? id : data.items[0]?.id ?? null);
  }, [api, page, status, defect, query]);
  useEffect(() => { let active = true; setD(null); setSelected({});
    const t = window.setTimeout(() => { if (active) load().catch((e) => setError(e.message)); }, 250);
    return () => { active = false; requestSeq.current++; window.clearTimeout(t); };
  }, [load]);
  const current = d?.items.find((x) => x.id === focus);
  useEffect(() => { let active = true; setVersions([]); setCompare(""); setRefIndex(0);
    if (focus != null) api.history(focus).then((v) => { if (active) setVersions(v.versions); }).catch((e) => ui.toast(e.message));
    return () => { active = false; };
  }, [api, focus, ui]);
  const act = async (action: "accept" | "reject" | "edit", one = false) => {
    if (busy) return;
    const items = one && current ? [current] : Object.values(selected);
    if (!items.length) return;
    if (action === "edit" && comment.trim().length < 3) { ui.toast("Опишите общую правку"); return; }
    setBusy(true);
    try {
      const result = await api.reviewBatch(items.map((i) => ({ frame_id: i.id, generation_id: i.generation })), action, comment.trim());
      setSelected((s) => Object.fromEntries(Object.entries(s).filter(([id]) => !result.done.includes(+id))));
      const next = d?.items.find((x) => x.id !== focus && !result.done.includes(x.id));
      if (one) setFocus(next?.id ?? null);
      setError(result.errors.map((x) => `${x.frame_id}: ${x.error}`).join("; "));
      ui.toast(`Обработано: ${result.done.length}; ошибок: ${result.errors.length}`);
      await load(); await reload();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  useEffect(() => {
    const keys = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,select,button,[contenteditable=true]") || busy || e.repeat) return;
      if (e.key === "1") { e.preventDefault(); void act("accept", true); }
      if (e.key === "2") { e.preventDefault(); void act("reject", true); }
      if (["ArrowLeft", "ArrowRight"].includes(e.key) && d) {
        e.preventDefault(); const i = d.items.findIndex((x) => x.id === focus), n = i + (e.key === "ArrowRight" ? 1 : -1);
        if (d.items[n]) setFocus(d.items[n].id);
      }
    };
    document.addEventListener("keydown", keys); return () => document.removeEventListener("keydown", keys);
  });
  const change = (fn: () => void) => { fn(); setPage(1); setSelected({}); };
  return <section className="page review-desk"><h1>Приёмка кадров</h1>
    <div className="row wrap"><input aria-label="Поиск в приёмке" placeholder="Артикул или название" value={query} onChange={(e) => change(() => setQuery(e.target.value))} />
      <select aria-label="Статус кадра" value={status} onChange={(e) => change(() => setStatus(e.target.value))}>
        <option value="review">Брак по мнению ИИ</option><option value="unchecked">Без проверки</option><option value="pass">Прошли ИИ</option><option value="accepted">Приняты вручную</option><option value="all">Все готовые</option>
      </select>
      <select aria-label="Причина брака" value={defect} onChange={(e) => change(() => setDefect(e.target.value))}>
        <option value="">Все причины</option>{Object.entries({ identity: "Товар и цвет", quantity: "Количество", anatomy: "Анатомия", text: "Текст и логотип", composition: "Композиция", technical: "Технический брак" }).map(([k,v]) => <option key={k} value={k}>{v}</option>)}
      </select><button onClick={() => load().catch((e) => setError(e.message))}>Обновить</button>
    </div>
    {error && <p role="alert" className="err-text">{error}</p>}
    <div className="row wrap"><b>Выбрано {Object.keys(selected).length}</b>
      <button disabled={busy || !d} onClick={() => setSelected(Object.fromEntries((d?.items || []).map((i) => [i.id, i])))}>Выбрать страницу</button>
      <button disabled={busy} onClick={() => setSelected({})}>Снять выбор</button>
      <input aria-label="Общее замечание" placeholder="Общее замечание / инструкция правки" value={comment} onChange={(e) => setComment(e.target.value)} />
      <button disabled={busy || !Object.keys(selected).length} onClick={() => act("accept")}>Принять выбранные</button>
      <button disabled={busy || !Object.keys(selected).length} onClick={() => act("reject")}>Отклонить</button>
      <button disabled={busy || !Object.keys(selected).length} onClick={() => act("edit")}>Править выбранные</button>
    </div>
    {!d ? <p>Загрузка…</p> : <>
      <div className="review-strip">{d.items.map((i) => <div key={i.id} className={focus === i.id ? "on" : ""}>
        <label><input type="checkbox" checked={!!selected[i.id]} onChange={(e) => setSelected((s) => { const next = { ...s }; if(e.target.checked) next[i.id] = i; else delete next[i.id]; return next; })} />{i.sku} · {i.position}</label>
        <button onClick={() => setFocus(i.id)}><img src={assetUrl(i.asset, 240)} alt={`${i.sku}, кадр ${i.position}`} /></button>
      </div>)}</div>
      {current ? <>
        <h2>{current.sku} · кадр {current.position}</h2>
        <div className="row wrap"><label>Сравнить с <select value={compare} onChange={(e) => setCompare(e.target.value)}>
          <option value="">Исходным фото товара</option>{versions.filter((v) => v.asset && v.id !== current.generation).map((v) => <option key={v.id} value={v.asset!}>Версия #{v.id}{v.edit ? ` · ${v.edit}` : ""}</option>)}
        </select></label>{!compare && current.references.map((a,i) => <button key={a} onClick={() => setRefIndex(i)} className={i === refIndex ? "on" : ""}>Фото {i+1}</button>)}</div>
        <CompareImages left={compare || current.references[refIndex]} right={current.asset} leftLabel={compare ? "Предыдущая версия" : "Референс товара"} />
        <ul>{current.defects.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
        {!current.defects.length && <p className="hint">{current.status === "unchecked" ? "ИИ-проверка не выполнена" : "Замечаний ИИ нет"}</p>}
        <div className="row"><button disabled={busy} onClick={() => act("accept", true)}>Принять и далее (1)</button><button disabled={busy} onClick={() => act("reject", true)}>Брак и далее (2)</button></div>
      </> : <p>Кадров по выбранным условиям нет.</p>}
      <div className="row pagination"><button disabled={page <= 1 || busy} onClick={() => setPage((n) => n-1)}>←</button>
        <span>Страница {page} · кадров {d.total}</span><button disabled={page * 24 >= d.total || busy} onClick={() => setPage((n) => n+1)}>→</button></div>
    </>}
    <p className="hint">1 — принять, 2 — отклонить, ← → — следующий кадр. Изменившиеся версии пропускаются с объяснением.</p>
  </section>;
}
