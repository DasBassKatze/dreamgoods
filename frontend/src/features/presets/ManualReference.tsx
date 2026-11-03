import { useEffect, useRef, useState } from "react";
import type { ManualItem, StyleRef } from "../../api/types";
import { assetUrl } from "../../api/client";
import { useProject } from "../../ProjectContext";

/** Реиспользует очередь, оплату и проверку доступа референсов клиента. */
export function ManualReference({ item, onChange, onBusy, locked }: {
  locked: boolean; item: ManualItem; onChange: (patch: Partial<ManualItem>) => void; onBusy: (busy: boolean) => void;
}) {
  const { api } = useProject();
  const [refs, setRefs] = useState<StyleRef[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const ref = refs.find(r => r.id === item.reference_id);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const result = await api.styles();
        if (!alive) return;
        setRefs(result.refs);
        if (result.refs.some(r => r.id === item.reference_id && r.job?.state === "running")) {
          timer = setTimeout(load, 2000);
        }
      } catch (e) { if (alive) setError(String(e)); }
    };
    void load();
    return () => { alive = false; clearTimeout(timer); };
  }, [api, item.reference_id, refresh]);
  const action = async (fn: () => Promise<void>) => {
    setError(""); setBusy(true); onBusy(true);
    try { await fn(); setRefresh(v => v + 1); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); onBusy(false); }
  };
  const upload = (file: File) => action(async () => {
    if (file.size > 20 * 1024 * 1024) throw new Error("Максимальный размер референса — 20 МБ");
    const created = await api.createStyle({ name: item.title || "Референс метода", note: "Взять композицию, ракурс, свет и настроение; сохранить товар с исходных фото." });
    try { await api.uploadStylePhoto(created.id, file); }
    catch (e) { await api.archiveStyle(created.id).catch(() => {}); throw e; }
    onChange({ reference_id: created.id, reference_description: "" });
  });
  return <div className="manual-reference">
    <div className="row">
      <b>Референс метода</b>
      <button disabled={busy || locked} onClick={() => input.current?.click()}>{busy ? "Загрузка…" : "Загрузить фото"}</button>
      <input hidden ref={input} type="file" accept="image/jpeg,image/png,image/webp" onChange={e => {
        const file = e.target.files?.[0]; e.target.value = ""; if (file) void upload(file);
      }} />
      <select aria-label="Референс метода" value={item.reference_id || 0} disabled={busy || locked}
        onChange={e => onChange({ reference_id: Number(e.target.value), reference_description: "" })}>
        <option value={0}>Без референса</option>
        {refs.filter(r => r.photos.length).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
      {!!item.reference_id && <button disabled={busy || locked} onClick={() => onChange({ reference_id: 0, reference_description: "" })}>Убрать</button>}
    </div>
    {ref && <>
      <div className="row">
        {ref.photos.slice(0, 1).map(ph => <img key={ph.id} src={assetUrl(ph.asset, 400)} alt="Референс метода" style={{ width: 130, maxHeight: 150, objectFit: "contain" }} />)}
        <button disabled={busy || locked || ref.job?.state === "running"} onClick={() => void action(async () => { await api.describeStyle(ref.id); })}>
          {ref.job?.state === "running" ? "ИИ описывает…" : "Описать с ИИ · платно"}
        </button>
        {ref.description && <button disabled={busy || locked} onClick={() => onChange({ reference_description: ref.description })}>Использовать ИИ-описание</button>}
      </div>
      {ref.description && ref.description !== item.reference_description && <p className="hint">ИИ: {ref.description}</p>}
      {ref.job?.state === "error" && <p role="alert">{ref.job.error || "Не удалось описать референс. Можно повторить."}</p>}
    </>}
    {!!item.reference_id && <textarea className="short" aria-label="Описание референса" placeholder="Что взять из референса: ракурс, композицию, свет, позу… Можно написать вручную или применить ИИ-описание."
      value={item.reference_description || ""} onChange={e => onChange({ reference_description: e.target.value })} />}
    <p className="hint">Фото и описание применяются только к этому методу. Товар берётся с исходных фото. Обложка следует правилам площадки. Загрузка бесплатна, ИИ-разбор оплачивается отдельно.</p>
    {error && <p role="alert">{error}</p>}
  </div>;
}
