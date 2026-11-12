import { useEffect, useRef, useState } from "react";
import { useDeleteProducts } from "../hooks/useDeleteProducts";
import { useActions } from "../hooks/useActions";
import { useProject } from "../ProjectContext";
import { useGenerationSelection } from "../features/generate/GenerationSelection";
import { matchesFilter } from "./ProductList";
import { useUI } from "./ui";
import { Icon } from "../layout/Icon";

export type Filter = "all" | "todo" | "review" | "err";

export function Toolbar({ filter, onFilter }: { filter: Filter; onFilter: (f: Filter) => void }) {
  const { state } = useProject();
  const FILTERS: [Filter, string][] = [["all", "Все товары"], ["todo", "Нужны кадры"], ["review", "Требуют решения"], ["err", "С ошибками"]];
  return <div className="bar">
    <div className="stat"><b>{state.totals.done}</b><span>/ {state.totals.total} кадров готово</span>
      <div className="progress"><i style={{ width: `${state.totals.total ? state.totals.done / state.totals.total * 100 : 0}%` }} /></div></div>
    <span className="spacer" /><div className="seg" role="group" aria-label="Фильтр товаров">
      {FILTERS.map(([key, name]) => { const count = state.products.filter(p => matchesFilter(p, key)).length;
        return <button key={key} className={filter === key ? "on" : ""} aria-pressed={filter === key} onClick={() => onFilter(key)}>{name}<span className="cnt-pill">{count}</span></button>; })}
    </div>
  </div>;
}

export function ListBar() {
  const remove = useDeleteProducts();
  const { state, selected, setSelected, pickedFrames, setPicked } = useProject();
  const { selectedIds, visibleIds, hidden } = useGenerationSelection();
  const input = useRef<HTMLInputElement>(null);
  const checked = visibleIds.length > 0 && visibleIds.every(id => selected.has(id));
  const some = visibleIds.some(id => selected.has(id));
  useEffect(() => { if (input.current) input.current.indeterminate = some && !checked; }, [some, checked]);
  const toggleVisible = (on: boolean) => {
    const next = new Set(selectedIds);
    visibleIds.forEach(id => on ? next.add(id) : next.delete(id));
    setSelected([...next]);
  };
  return <div className="listbar">
    <div className="selection-row">
      <label className="check"><input ref={input} type="checkbox" checked={checked} disabled={!visibleIds.length} onChange={e => toggleVisible(e.target.checked)} /> Выбрать найденные ({visibleIds.length})</label>
      <span className="selection-count" aria-live="polite">Выбрано: {selectedIds.length}{hidden > 0 && <strong> · скрыто фильтром: {hidden}</strong>}</span>
      {selectedIds.length > 0 && <button className="danger" onClick={() => void remove(selectedIds)}>Удалить выбранные</button>}
      {selectedIds.length > 0 && <button className="link" onClick={() => setSelected([])}>Снять выбор</button>}
      <span className="spacer" /><details className="selection-menu"><summary>Другие действия</summary><div>
        <button onClick={() => setSelected(state.products.map(p => p.id))}>Выбрать весь проект ({state.products.length})</button>
      </div></details>
    </div>
    {pickedFrames.size > 0 && <div className="hint">Выделено кадров для скачивания: {pickedFrames.size} <button className="link" onClick={() => setPicked([])}>Снять выделение кадров</button></div>}

  </div>;
}

export function QualityTools() {
  const { state } = useProject();
  const { ids, label } = useGenerationSelection();
  const { checkReady, profiles } = useActions();
  const ui = useUI();
  const newProfiles = async () => {
    const targets = state.products.filter(p => ids.includes(p.id) && !p.total).map(p => p.id);
    if (!targets.length) { ui.toast("У товаров из этой области уже есть план кадров"); return; }
    if (await ui.confirm({ title: "Подготовить планы кадров", text: `ИИ проанализирует фото ${targets.length} товаров и подготовит описания кадров. Анализ платный. Генерация изображений сейчас не запускается.`, ok: "Подготовить" })) await profiles(targets, true);
  };
  return <>
      <p className="hint">Область действий: {label}. Смена режима интерфейса эти настройки не меняет.</p>
      <div className="row wrap"><button disabled={!ids.length} onClick={() => void checkReady([...ids])}><Icon name="search" size={15} /> Проверить готовые · платно</button>
        <button disabled={!ids.length} onClick={() => void newProfiles()}><Icon name="spark" size={15} /> Подготовить планы кадров · платно</button></div>

  </>;
}

export function QualitySwitches() {
  const { state, api, reload, run } = useProject();
  const [pending, setPending] = useState<{ key: "qc_enabled" | "qc_autoregen"; value: boolean } | null>(null);
  const saving = pending !== null;
  const qcEnabled = pending?.key === "qc_enabled" ? pending.value : state.settings.qc_enabled;
  const autoregen = pending?.key === "qc_autoregen" ? pending.value : state.settings.qc_autoregen;
  const toggle = (key: "qc_enabled" | "qc_autoregen", value: boolean) => {
    if (saving) return;
    setPending({ key, value });
    void run(async () => { await api.saveSettings({ [key]: value }); await reload(); }).finally(() => setPending(null));
  };
  return <div className="quick-quality-controls" role="group" aria-label="Проверка и перегенерация" aria-busy={saving}>
    <label className="check"><input type="checkbox" checked={qcEnabled} disabled={saving}
      onChange={e => toggle("qc_enabled", e.target.checked)} /> ИИ-проверка</label>
    <label className="check" title={qcEnabled ? "Автоматически переделывать кадры, не прошедшие ИИ-проверку. Переделки оплачиваются." : "Для автоматической переделки включите ИИ-проверку"}>
      <input type="checkbox" checked={autoregen} disabled={saving || !qcEnabled}
        onChange={e => toggle("qc_autoregen", e.target.checked)} /> Автоматически переделывать брак · платно</label>
    {saving && <span role="status">Сохраняю…</span>}
  </div>;
}
