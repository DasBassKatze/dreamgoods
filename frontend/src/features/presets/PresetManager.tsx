import { useCallback, useEffect, useState } from "react";
import type { Preset, PresetListing } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";
import { PresetApply } from "./PresetApply";
import { PresetEditor, type Draft } from "./PresetEditor";

const EMPTY: Draft = { name: "", description: "", quality: "standard", custom: {},
  plan: { studio: 4, detail: 1, worn: 2, full: 1, lifestyle: 0 }, market: { key: "wb", cover: true }, strictness: "normal",
  plan_mode: "auto", manual: [], block_models: {}, brief: "" };

/** Пресеты генерации: уровень качества + план кадров. Общие для всей организации; применяются к товарам проекта. */
export function PresetManager({ onClose, initialApply }: { onClose: () => void; initialApply?: boolean }) {
  const { api, reload, run, state } = useProject();
  const ui = useUI();
  const [data, setData] = useState<PresetListing | null>(null);
  const [current, setCurrent] = useState<number | "new" | null>(null);
  const [applying, setApplying] = useState(!!initialApply);

  const load = useCallback(async () => {
    const r = await api.presets();
    setData(r);
    setCurrent((c) => (c === "new" || (c != null && r.presets.some((p) => p.id === c)) ? c : r.default_id || r.presets[0]?.id || "new"));
    return r;
  }, [api]);

  useEffect(() => {
    load().catch((e) => ui.toast(e.message));
  }, [load, ui]);

  const preset: Preset | undefined = data?.presets.find((p) => p.id === current);

  // общий пресет сервиса пользователь не меняет — сохраняется его копия в кабинете
  const readonly = !!preset?.shared && !state.admin;
  const save = (d: Draft) =>
    run(async () => {
      const asNew = current === "new" || readonly;
      const body = readonly && d.name === preset?.name ? { ...d, name: `${d.name} (моя копия)` } : d;
      const r = await api.savePreset(asNew ? null : (current as number), body);
      ui.toast(readonly ? "Сохранено как ваш пресет" : "Пресет сохранён");
      if (asNew && "id" in r) setCurrent(r.id);
      await load();
      await reload();
    });

  const remove = () =>
    run(async () => {
      if (!preset) return;
      const ok = await ui.confirm({ text: `Удалить пресет «${preset.name}»? Товары с ним вернутся к пресету проекта.`, ok: "Удалить" });
      if (!ok) return;
      await api.archivePreset(preset.id);
      setCurrent(null);
      await load();
      await reload();
    });

  return (
    <Modal title="Пресеты генерации" width={1180} onClose={onClose}>
      {!data ? <div className="empty">Загрузка…</div> : (
        <div className="presets">
          <div className="preset-list">
            {data.presets.map((p) => (
              <button key={p.id} className={`preset-item ${current === p.id ? "on" : ""}`} onClick={() => { setCurrent(p.id); setApplying(false); }}>
                <b>{p.name}</b>
                {p.shared && <span className="tag">{state.admin ? "пресет студии" : "общий"}</span>}
                <span className="hint">{data.quality.find((q) => q.key === p.quality)?.name} · {p.total} кадр.
                  {p.is_default ? " · проект" : ""}{p.products ? ` · товаров ${p.products}` : ""}</span>
              </button>
            ))}
            <button className={`preset-item new ${current === "new" ? "on" : ""}`} onClick={() => { setCurrent("new"); setApplying(false); }}>＋ Новый пресет</button>
          </div>
          <div className="preset-body">
            {applying && preset ? (
              <PresetApply listing={data} preset={preset} onBack={() => setApplying(false)}
                onDone={async () => { setApplying(false); await load(); }} onRefresh={load} />
            ) : current === "new" || preset ? (
              <>
              {readonly && <div className="note-box">Это общий пресет сервиса. Его можно применять как есть, а если поменять —
                сохранится ваша копия.</div>}
              <PresetEditor key={String(current)} listing={data} initial={preset ? { name: preset.name, description: preset.description,
                quality: preset.quality, custom: preset.custom, plan: preset.plan, market: preset.market,
                strictness: preset.strictness, plan_mode: preset.plan_mode, manual: preset.manual,
                block_models: preset.block_models, shared: !!preset.shared, brief: preset.brief || "" } : EMPTY}
                isNew={current === "new"} onSave={save} onDelete={preset && !readonly ? remove : undefined}
                onApply={preset ? () => setApplying(true) : undefined} />
              </>
            ) : <div className="empty">Выберите пресет слева</div>}
          </div>
        </div>
      )}
    </Modal>
  );
}
