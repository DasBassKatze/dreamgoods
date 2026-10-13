import { useCallback, useEffect, useState } from "react";
import type { CatalogModel } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";

export type CatalogKind = "image" | "qc";
export interface CatalogPick {
  kind: CatalogKind;
  id: string;
  providers: string;
  seq: number;
}

const cache: Partial<Record<CatalogKind, CatalogModel[]>> = {};

export function ModelCatalog({ kind, onClose, onPicked }: { kind: CatalogKind; onClose: () => void; onPicked: (p: CatalogPick) => void }) {
  const { state, api, reload, run } = useProject();
  const ui = useUI();
  const [models, setModels] = useState<CatalogModel[] | null>(cache[kind] || null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [onlyRefs, setOnlyRefs] = useState(true);
  const qc = kind === "qc";
  const s = state.settings;

  const load = useCallback(async (refresh: boolean) => {
    setModels(null);
    setError("");
    try {
      const r = await api.catalog(kind, refresh);
      cache[kind] = r.models || [];
      setModels(cache[kind]!);
      setError(r.error || "");
    } catch (e) {
      setModels([]);
      setError((e as Error).message);
    }
  }, [api, kind]);

  useEffect(() => {
    if (!cache[kind]) load(false);
  }, [kind, load]);

  const pick = (m: CatalogModel, provider = "") =>
    run(async () => {
      if (!qc && m.refs === false) {
        const ok = await ui.confirm({ text: "Эта модель, судя по каталогу, не принимает фото на вход — референсы не будут учтены. Всё равно выбрать?" });
        if (!ok) return;
      }
      await api.saveSettings(qc ? { qc_model: m.id } : { model: m.id, providers: provider });
      onPicked({ kind, id: m.id, providers: provider, seq: Date.now() });
      ui.toast(qc ? `Модель проверки: ${m.id}` : `Модель: ${m.id}${provider ? " · " + provider : " · провайдер выберет Polza"}`);
      await reload();
      onClose();
    });

  const cur = qc ? s.qc_model : s.model;
  const curP = qc ? [] : (s.providers || "").split(",").map((x) => x.trim()).filter(Boolean);
  const q = query.trim().toLowerCase();
  const list = (models || []).filter(
    (m) => (qc || !onlyRefs || m.refs) && (!q || m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)),
  );

  return (
    <Modal title={qc ? "Модели для ИИ-проверки (принимают картинки)" : "Модели генерации изображений на Polza"} width={900} onClose={onClose}
      actions={<button onClick={() => load(true)}>⟳ Обновить</button>}>
      <div className="row">
        <input type="text" className="grow" autoFocus placeholder="Поиск: banana, seedream, gpt…" value={query} onChange={(e) => setQuery(e.target.value)} />
        {!qc && <label><input type="checkbox" checked={onlyRefs} onChange={(e) => setOnlyRefs(e.target.checked)} /> только с референсами</label>}
      </div>
      <div className="hint mb8">
        {qc ? "Клик по модели — выбрать её для проверки кадров." : "Клик по модели — выбрать её (провайдера выберет Polza). Клик по провайдеру — модель именно с этим провайдером."} Цены — из каталога Polza.
      </div>
      {error && <div className="err-text">{error}</div>}
      <div className="mplist">
        {models == null ? (
          <div className="empty">Загрузка каталога…</div>
        ) : !list.length ? (
          <div className="empty">Ничего не найдено</div>
        ) : (
          list.map((m) => (
            <div key={m.id} className={`mp ${m.id === cur ? "cur" : ""}`}>
              <div>
                <span className="nm" onClick={() => pick(m)}>{m.name}</span> <code>{m.id}</code>{" "}
                {!qc && (m.refs ? <span className="tag">референсы ✓</span> : <span className="tag bad">без референсов</span>)}
              </div>
              <div className="hint">{m.price}</div>
              {!qc && (
                <div className="pv">
                  {m.providers.length ? m.providers.map((p) => (
                    <button key={p.name} className={`pchip ${m.id === cur && curP.includes(p.name) ? "cur" : ""}`} onClick={() => pick(m, p.name)}>
                      {p.name}{p.price ? ` · ${p.price}` : ""}
                    </button>
                  )) : <span className="hint">провайдеры не указаны</span>}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}
