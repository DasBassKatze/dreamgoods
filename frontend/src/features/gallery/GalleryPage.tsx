import { useMemo, useState } from "react";
import type { Dialogs } from "../../App";
import { assetUrl, downloadUrl } from "../../api/client";
import { Icon } from "../../layout/Icon";
import { QC_LABEL, isBusy, pad, plural, qcStatus } from "../../lib/format";
import { useProject } from "../../ProjectContext";

type Kind = "all" | "ok" | "manual" | "unchecked" | "review" | "rejected";
const KINDS: [Kind, string][] = [["all", "Все"], ["ok", "Прошли проверку"], ["manual", "Приняты вручную"], ["unchecked", "Без проверки"], ["review", "На проверке"], ["rejected", "Отклонённые"]];

/** Вкладка «Галерея»: все готовые кадры проекта одной сеткой. */
export function GalleryPage({ dialogs }: { dialogs: Dialogs }) {
  const { state, api, pickedFrames, togglePicked, setPicked } = useProject();
  const [kind, setKind] = useState<Kind>("all");
  const [query, setQuery] = useState("");
  const [big, setBig] = useState(false);

  const all = useMemo(() => state.products.flatMap((p) => p.frames.filter((f) => f.asset).map((f) => ({ p, f }))), [state.products]);
  const count = (k: Kind) => all.filter(({ f }) => match(k, qcStatus(f))).length;
  const q = query.trim().toLowerCase();
  const shown = all.filter(({ p, f }) => match(kind, qcStatus(f)) && (!q || `${p.sku} ${p.name || ""} ${f.block}`.toLowerCase().includes(q)));
  const picked = shown.filter(({ f }) => pickedFrames.has(f.id));

  return (
    <div className="page gallery">
      <div className="page-head">
        <h1>Галерея</h1>
        <span className="hint">{all.length} {plural(all.length, "готовый кадр", "готовых кадра", "готовых кадров")} · {state.project.name}</span>
        <span className="spacer" />
        {pickedFrames.size > 0 && (
          <>
            <button className="link" onClick={() => setPicked([])}>снять выделение</button>
            <a className="btn primary" href={api.exportUrl("picked", { frames: [...pickedFrames] })}>
              <Icon name="download" size={16} /> Скачать выделенные ({pickedFrames.size})
            </a>
          </>
        )}
      </div>
      <div className="gal-bar">
        <span className="seg">
          {KINDS.map(([k, name]) => (
            <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>
              {name}<span className="cnt-pill">{count(k)}</span>
            </button>
          ))}
        </span>
        <input className="search" type="search" aria-label="Поиск кадров в галерее" placeholder="Артикул или блок…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="spacer" />
        {shown.length > 0 && (
          <button className="link" onClick={() => { const next = new Set(pickedFrames); shown.forEach(({ f }) => picked.length === shown.length ? next.delete(f.id) : next.add(f.id)); setPicked([...next]); }}>
            {picked.length === shown.length ? "снять все" : "выделить все"}
          </button>
        )}
        <button className="icon-btn" title={big ? "Мельче" : "Крупнее"} onClick={() => setBig(!big)}><Icon name={big ? "products" : "image"} size={16} /></button>
      </div>
      {!shown.length ? (
        <div className="empty">{all.length ? "Под фильтр ничего не подходит" : "Готовых кадров пока нет — запустите генерацию на вкладке «Генерация»."}</div>
      ) : (
        <div className={`gal-grid ${big ? "big" : ""}`}>
          {shown.map(({ p, f }) => {
            const st = qcStatus(f);
            const on = pickedFrames.has(f.id);
            return (
              <figure key={f.id} className={`gal-item ${on ? "picked" : ""}`}>
                <button className="gal-img" onClick={(e) => ((e.ctrlKey || e.metaKey) ? togglePicked(f.id, !on) : dialogs.openFrame(p.id, f.id))}>
                  <img loading="lazy" src={assetUrl(f.asset!, big ? 640 : 400)} alt="" />
                  {isBusy(f) ? <span className="badge">в работе</span> : st && st !== "unchecked" ? <span className={`badge q-${st}`}>{QC_LABEL[st]}</span> : null}
                </button>
                <label className="pick" title="Выделить для скачивания"><input type="checkbox" checked={on} onChange={(e) => togglePicked(f.id, e.target.checked)} /></label>
                <a className="gal-dl" href={downloadUrl(f.asset!, `${p.sku}_${pad(f.i)}`)} title="Скачать оригинал"><Icon name="download" size={15} /></a>
                <figcaption><b>{p.sku}</b><small>{pad(f.i)} · {f.block}</small></figcaption>
              </figure>
            );
          })}
        </div>
      )}
    </div>
  );
}

function match(k: Kind, st: string) {
  switch (k) {
    case "ok": return st === "pass" || st === "accepted";
    case "manual": return st === "accepted";
    case "unchecked": return st === "" || st === "unchecked";
    case "review": return st === "review";
    case "rejected": return st === "rejected";
    default: return true;
  }
}
