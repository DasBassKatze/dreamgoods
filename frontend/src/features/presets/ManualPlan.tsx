import type { BlockKey, CatalogModel, ManualItem, PresetListing } from "../../api/types";
import { ModelSelect } from "./ModelSelect";

const TYPE_RU: Record<BlockKey, string> = {
  studio: "товар (без людей)",
  detail: "деталь крупно",
  worn: "на человеке крупно",
  full: "на человеке в полный рост",
  lifestyle: "лайфстайл без людей",
};

const EXAMPLES: Omit<ManualItem, "model">[] = [
  { title: "Мрамор сверху", prompt: "{товар} на светлом мраморном столе, вид сверху, мягкий дневной свет", block: "studio", count: 1 },
  { title: "Шаг по брусчатке", prompt: "крупно ноги в движении, шаг по мокрой брусчатке, вечерние огни", block: "worn", count: 2 },
  { title: "Городской образ", prompt: "девушка в пальто стоит у витрины кафе, осень, тёплый свет", block: "full", count: 1 },
];

interface Props {
  listing: PresetListing;
  items: ManualItem[];
  onChange: (items: ManualItem[]) => void;
  models: CatalogModel[] | null;
  baseModel: string;
  blockModels?: Partial<Record<string, string>>;
  resolution?: string;
}

/** Ручной план: свои методы съёмки — название, промпт, тип кадра, количество, своя модель. */
export function ManualPlan({ listing, items, onChange, models, baseModel, blockModels, resolution }: Props) {
  const set = (i: number, patch: Partial<ManualItem>) => onChange(items.map((it, n) => (n === i ? { ...it, ...patch } : it)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= items.length) return;
    const next = [...items];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  const total = items.reduce((a, b) => a + (b.count || 0), 0);

  return (
    <div className="manual-plan">
      <div className="hint mb8">
        Каждый метод — ваш промпт съёмки (можно по-русски). Описание товара, «товар как на фото», правила сторон, анатомию и
        обложку площадки программа добавит сама. <code>{"{товар}"}</code> в тексте заменится на название товара.
        Тип кадра нужен, чтобы подключить модель клиента, оформление и проверку.
      </div>
      {items.map((it, i) => (
        <div key={i} className="manual-item">
          <div className="row nowrap">
            <span className="plan-n">{i + 1}</span>
            <input type="text" className="mi-title" value={it.title} placeholder="название метода" onChange={(e) => set(i, { title: e.target.value })} />
            <select value={it.block} onChange={(e) => set(i, { block: e.target.value as BlockKey })}>
              {listing.blocks.map((b) => <option key={b.key} value={b.key}>{TYPE_RU[b.key]}</option>)}
            </select>
            <div className="plan-row">
              <button onClick={() => set(i, { count: Math.max(1, it.count - 1) })} disabled={it.count <= 1}>−</button>
              <b className="plan-n">{it.count}</b>
              <button onClick={() => set(i, { count: Math.min(8, it.count + 1) })} disabled={it.count >= 8}>＋</button>
              <span className="hint">шт.</span>
            </div>
            <span className="spacer" />
            <button title="Выше" onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
            <button title="Ниже" onClick={() => move(i, 1)} disabled={i === items.length - 1}>↓</button>
            <button className="danger" title="Удалить метод" onClick={() => onChange(items.filter((_, n) => n !== i))}>✕</button>
          </div>
          <textarea className="short" value={it.prompt} placeholder="как снимать: сцена, ракурс, свет, поза…"
            onChange={(e) => set(i, { prompt: e.target.value })} />
          <div className="row nowrap">
            <span className="hint">Модель:</span>
            <ModelSelect value={it.model} onChange={(m) => set(i, { model: m })} models={models}
              emptyLabel={`как у блока «${TYPE_RU[it.block]}»`} baseModel={baseModel}
              fallback={blockModels?.[it.block] || baseModel} resolution={resolution} />
          </div>
        </div>
      ))}
      <div className="row">
        <button onClick={() => onChange([...items, { title: "", prompt: "", block: "studio", count: 1, model: "" }])}>＋ Метод съёмки</button>
        {!items.length && EXAMPLES.map((x) => (
          <button key={x.title} className="pchip" onClick={() => onChange([...items, { ...x, model: "" }])}>пример: {x.title}</button>
        ))}
        <span className="spacer" />
        <span className="hint">итого {total} кадр(ов) · максимум 12 методов и 30 кадров</span>
      </div>
    </div>
  );
}
