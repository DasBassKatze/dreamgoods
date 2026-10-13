import type { CatalogModel } from "../../api/types";

/** Выбор модели генерации из каталога Polza (с ценой). Пустое значение — «как выше по цепочке». */
export function ModelSelect({ value, onChange, models, emptyLabel, baseModel }: {
  value: string; onChange: (v: string) => void; models: CatalogModel[] | null; emptyLabel: string; baseModel: string;
}) {
  const list = (models || []).filter((m) => m.refs !== false);
  const known = !value || list.some((m) => m.id === value);
  return (
    <select className="model-select" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{emptyLabel}</option>
      {!known && <option value={value}>{value}</option>}
      {list.map((m) => (
        <option key={m.id} value={m.id}>{m.name}{m.id === baseModel ? " (основная)" : ""}{m.price ? ` — ${m.price}` : ""}</option>
      ))}
      {models === null && <option disabled>загрузка каталога…</option>}
    </select>
  );
}
