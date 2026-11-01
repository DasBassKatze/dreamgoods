import type { CatalogModel } from "../../api/types";

const RES_RANK: Record<string, number> = { "1K": 1, "2K": 2, "4K": 3 };

/** Выбор модели генерации из каталога Polza (с ценой) и описание выбранной модели для пользователя.
 *  Пустое значение — «как выше по цепочке» (fallback: какая модель тогда сработает). */
export function ModelSelect({ value, onChange, models, emptyLabel, baseModel, fallback, resolution }: {
  value: string; onChange: (v: string) => void; models: CatalogModel[] | null; emptyLabel: string; baseModel: string;
  fallback?: string; resolution?: string;
}) {
  const list = (models || []).filter((m) => m.refs !== false);
  const known = !value || list.some((m) => m.id === value);
  const shownId = value || fallback || "";
  const shown = (models || []).find((m) => m.id === shownId);
  const short = (id: string) => (models || []).find((m) => m.id === id)?.name || id.split("/").pop();
  const upscaled = !!(shown?.max_res && resolution && (RES_RANK[resolution] || 0) > (RES_RANK[shown.max_res] || 0));
  return (
    <div className="model-pick">
      <select className="model-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{emptyLabel}{fallback ? ` — ${short(fallback)}` : ""}</option>
        {!known && <option value={value}>{value}</option>}
        {list.map((m) => (
          <option key={m.id} value={m.id}>{m.name}{m.id === baseModel ? " (основная)" : ""}{m.price ? ` — ${m.price}` : ""}</option>
        ))}
        {models === null && <option disabled>загрузка каталога…</option>}
      </select>
      {shown && (shown.note || shown.max_res) && (
        <div className="model-note">
          {shown.note}
          {upscaled && <b> В пресете {resolution}: модель отдаст {shown.max_res}, кадр будет увеличен — для крупных кадров лучше модель посильнее.</b>}
        </div>
      )}
    </div>
  );
}
