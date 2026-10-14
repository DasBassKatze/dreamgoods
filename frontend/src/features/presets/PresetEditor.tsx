import { useEffect, useState } from "react";
import type { BlockKey, CatalogModel, ManualItem, PresetListing, PresetMarket, QualityKey, StrictnessKey } from "../../api/types";
import { ManualPlan } from "./ManualPlan";
import { ModelSelect } from "./ModelSelect";
import { rub } from "../../lib/format";
import { useProject } from "../../ProjectContext";

export interface Draft {
  name: string;
  description: string;
  quality: QualityKey;
  custom: Record<string, string | number | boolean>;
  plan: Record<BlockKey, number>;
  market: PresetMarket;
  strictness: StrictnessKey;
  plan_mode: "auto" | "manual";
  manual: ManualItem[];
  block_models: Partial<Record<BlockKey, string>>;
}

// подсказка «не стрелять из пушки по воробьям»: где обычно хватает модели попроще
const MODEL_TIP: Record<BlockKey, string> = {
  studio: "на белом фоне обычно хватает быстрой дешёвой модели",
  detail: "детали — простая сцена, подойдёт модель попроще",
  worn: "человек и анатомия — здесь сильная модель окупается",
  full: "человек целиком, сложная сцена — лучше сильная модель",
  lifestyle: "сцена без людей — средняя модель обычно справляется",
};

const BLOCK_HINT: Record<BlockKey, string> = {
  studio: "главное фото и ракурсы: спереди, сбоку, сзади, сверху, пара/комплект",
  detail: "фактура материала, фурнитура, подошва, принт — крупно",
  worn: "на человеке или в руках, крупно (для товаров без человека — в использовании)",
  full: "человек целиком с товаром; для товаров без человека — общий план сцены",
  lifestyle: "товар в интерьере или натюрморте, без людей",
};

interface Props {
  listing: PresetListing;
  initial: Draft;
  isNew: boolean;
  onSave: (d: Draft) => void;
  onDelete?: () => void;
  onApply?: () => void;
}

export function PresetEditor({ listing, initial, isNew, onSave, onDelete, onApply }: Props) {
  const { state, api } = useProject();
  const [d, setD] = useState<Draft>(initial);
  const [models, setModels] = useState<CatalogModel[] | null>(null);
  useEffect(() => {
    api.catalog("image").then((r) => setModels(r.models || [])).catch(() => setModels([]));
  }, [api]);
  const manual = d.plan_mode === "manual";
  const total = manual ? d.manual.reduce((a, b) => a + (b.count || 0), 0) : Object.values(d.plan).reduce((a, b) => a + (b || 0), 0);
  const baseModel = String(d.custom.model || state.settings.model);
  const resolution = String(d.quality === "custom" ? d.custom.resolution || state.settings.resolution
    : listing.quality.find((x) => x.key === d.quality)?.settings.resolution || state.settings.resolution);
  const stats = (b: BlockKey) => listing.model_stats.filter((x) => x.block === b);
  const q = listing.quality.find((x) => x.key === d.quality);
  const retries = d.quality === "custom" ? Number(d.custom.qc_retries ?? state.settings.qc_retries) : Number(q?.settings.qc_retries ?? 0);
  const avg = state.totals.avg_cost || 0;
  const changed = JSON.stringify(d) !== JSON.stringify(initial);
  const setPlan = (k: BlockKey, v: number) => setD({ ...d, plan: { ...d.plan, [k]: v } });
  const setCustom = (k: string, v: string | number | boolean) => setD({ ...d, custom: { ...d.custom, [k]: v } });
  const market = listing.markets.find((m) => m.key === d.market.key) || listing.markets[0];
  const setMarket = (m: Partial<PresetMarket>) => setD({ ...d, market: { ...d.market, ...m } });
  const coverOn = d.market.key !== "none" && d.market.cover;
  const coverProblem = coverOn && (manual ? !!d.manual.length && d.manual[0].block !== "studio" : !d.plan.studio);

  return (
    <div>
      <div className="form grid">
        <label className="form-label">Название</label>
        <input type="text" value={d.name} placeholder="например, Обувь — маркетплейс" onChange={(e) => setD({ ...d, name: e.target.value })} />
        <label className="form-label">Описание</label>
        <input type="text" value={d.description} placeholder="для кого и зачем этот пресет" onChange={(e) => setD({ ...d, description: e.target.value })} />

        <h4>Качество</h4>
        <label className="form-label">Уровень</label>
        <div className="quality-cards">
          {listing.quality.map((x) => (
            <label key={x.key} className={`quality-card ${d.quality === x.key ? "on" : ""}`}>
              <input type="radio" checked={d.quality === x.key} onChange={() => setD({ ...d, quality: x.key })} />
              <b>{x.name}</b>
              <span className="hint">{x.hint}</span>
            </label>
          ))}
        </div>
        {d.quality === "custom" && (
          <>
            <label className="form-label">Разрешение · перегенераций</label>
            <div>
              <div className="row nowrap">
                <select value={String(d.custom.resolution ?? "")} onChange={(e) => setCustom("resolution", e.target.value)}>
                  <option value="">как в настройках</option>
                  {[["1K", 900], ["2K", 1800], ["4K", 3600]].map(([r, px]) => <option key={r} value={r}>{r} · {px} px</option>)}
                </select>
                <input type="number" min={0} max={6000} step={100} value={Number(d.custom.out_side || 0) || ""} style={{ width: 110 }}
                  placeholder="своё, px" title="Своё разрешение: короткая сторона готового кадра, px. Пусто — по уровню 1K/2K/4K"
                  onChange={(e) => setCustom("out_side", +e.target.value || 0)} />
                <select value={String(d.custom.qc_retries ?? "")} onChange={(e) => setCustom("qc_retries", e.target.value === "" ? "" : +e.target.value)}>
                  <option value="">перегенераций — как в настройках</option>{[0, 1, 2, 3].map((n) => <option key={n} value={n}>до {n} перегенераций</option>)}
                </select>
                <label className="check"><input type="checkbox" checked={!!d.custom.qc_count} onChange={(e) => setCustom("qc_count", e.target.checked)} /> подсчёт</label>
              </div>
              <div className="hint mt6">разрешение — короткая сторона готового кадра. Если модель вернёт меньше (например, Nano Banana
                умеет только 1K), кадр увеличивается до него без перегенерации. Своё значение в px главнее уровня.</div>
            </div>
            <label className="form-label">Модель проверки</label>
            <input type="text" value={String(d.custom.qc_model ?? "")} placeholder={`пусто — ${state.settings.qc_model}`}
              onChange={(e) => setCustom("qc_model", e.target.value)} />
          </>
        )}

        <h4>Нейросеть генерации</h4>
        <label className="form-label">Основная модель</label>
        <div>
          <ModelSelect value={String(d.custom.model ?? "")} onChange={(m) => setCustom("model", m)} models={models}
            emptyLabel="по умолчанию" fallback={state.settings.model} baseModel={baseModel} resolution={resolution} />
          <div className="hint mt4">Делает все кадры, если ниже для блока не выбрана своя модель.</div>
        </div>
        <label className="form-label">По блокам</label>
        <div className="hint pt6">Простые кадры (белый фон, детали) можно делать дешёвой быстрой моделью, а сильную оставить для
          кадров с человеком. Пусто — основная модель. {manual ? "У ручного метода можно выбрать свою модель — она главнее." : ""}</div>
        {listing.blocks.map((b) => (
          <BlockModel key={b.key} label={b.name} tip={MODEL_TIP[b.key]} value={d.block_models[b.key] || ""} models={models} baseModel={baseModel}
            resolution={resolution} stats={stats(b.key)} onChange={(m) => setD({ ...d, block_models: { ...d.block_models, [b.key]: m } })} />
        ))}

        <h4>Площадка</h4>
        <label className="form-label">Для какой площадки</label>
        <div>
          <div className="seg wrap">
            {listing.markets.map((m) => (
              <button key={m.key} className={d.market.key === m.key ? "on" : ""}
                onClick={() => setD({ ...d, market: { key: m.key, cover: m.key !== "none" } })}>{m.name}</button>
            ))}
          </div>
          <div className="hint mt6">{market.hint}</div>
        </div>
        {d.market.key !== "none" && (
          <>
            <label className="form-label">Формат · мин. сторона</label>
            {d.market.key === "custom" ? (
              <div className="row nowrap">
                <select value={d.market.aspect || market.aspect} onChange={(e) => setMarket({ aspect: e.target.value })}>
                  {listing.aspects.map((a) => <option key={a}>{a}</option>)}
                </select>
                <input type="number" min={0} max={4096} step={100} value={d.market.min_side ?? market.min_side} style={{ width: 110 }}
                  onChange={(e) => setMarket({ min_side: +e.target.value || 0 })} /> <span className="hint">px — меньше считается браком техпроверки</span>
              </div>
            ) : <div className="hint pt6">{market.aspect} · кадр меньше {market.min_side} px по короткой стороне считается браком техпроверки</div>}
            <label className="form-label">Обложка</label>
            <div>
              <label className="check"><input type="checkbox" checked={d.market.cover} onChange={(e) => setMarket({ cover: e.target.checked })} /> первый
                кадр «на белом фоне» делать главным фото карточки по правилам площадки</label>
              {coverOn && d.market.key === "custom" && (
                <div className="ch-col mt6">
                  <input type="text" value={d.market.cover_bg ?? market.cover_bg} placeholder="фон обложки (англ.), например a pure white background"
                    onChange={(e) => setMarket({ cover_bg: e.target.value })} />
                  <input type="text" value={d.market.cover_fill ?? market.cover_fill} placeholder="заполнение кадра, например about 80% of the frame"
                    onChange={(e) => setMarket({ cover_fill: e.target.value })} />
                  <input type="text" value={d.market.cover_extra ?? market.cover_extra} placeholder="дополнительно, например no text, no logos"
                    onChange={(e) => setMarket({ cover_extra: e.target.value })} />
                </div>
              )}
              {coverProblem && <div className="err-text">Для обложки нужен хотя бы один кадр «на белом фоне»</div>}
            </div>
          </>
        )}

        <h4>Строгость ИИ-проверки</h4>
        <label className="form-label">Что считать браком</label>
        <div className="quality-cards">
          {listing.strictness.map((x) => (
            <label key={x.key} className={`quality-card ${d.strictness === x.key ? "on" : ""}`}>
              <input type="radio" checked={d.strictness === x.key} onChange={() => setD({ ...d, strictness: x.key })} />
              <b>{x.name}</b>
              <span className="hint">{x.hint}</span>
            </label>
          ))}
        </div>

        <h4>План кадров на один товар</h4>
        <label className="form-label">Режим</label>
        <div>
          <div className="seg">
            <button className={!manual ? "on" : ""} onClick={() => setD({ ...d, plan_mode: "auto" })}>Авто — кадры придумывает ИИ</button>
            <button className={manual ? "on" : ""} onClick={() => setD({ ...d, plan_mode: "manual" })}>Ручной — свои промпты</button>
          </div>
          <div className="hint mt6">{manual
            ? "Вы задаёте методы съёмки своими промптами и количество каждого; ИИ не придумывает ракурсы."
            : "Вы задаёте количество кадров по блокам, ИИ по фото товара придумывает каждый кадр."}</div>
        </div>
        {manual ? (
          <>
            <label className="form-label">Методы съёмки</label>
            <ManualPlan listing={listing} items={d.manual} onChange={(m) => setD({ ...d, manual: m })} models={models} baseModel={baseModel}
              blockModels={d.block_models} resolution={resolution} />
          </>
        ) : listing.blocks.map((b) => (
          <PlanRow key={b.key} label={b.name} hint={BLOCK_HINT[b.key]} max={b.max} value={d.plan[b.key] || 0} onChange={(v) => setPlan(b.key, v)} />
        ))}

        <label className="form-label">Итого</label>
        <div>
          <b>{total} кадр(ов) на товар</b>
          {avg > 0 && <span className="hint"> · ≈ {rub(total * avg)} на товар по средней цене кадра
            {retries > 0 ? `, с перегенерациями брака — до ${rub(total * avg * (1 + retries))}` : ""}</span>}
        </div>
      </div>
      <div className="row mt16">
        {onDelete && <button className="danger" onClick={onDelete}>Удалить</button>}
        <span className="spacer" />
        {onApply && !changed && <button onClick={onApply}>Применить к товарам…</button>}
        <button className="primary" disabled={!changed && !isNew || !total || !d.name.trim() || coverProblem} onClick={() => onSave(d)}>
          {isNew ? "Создать пресет" : "Сохранить"}
        </button>
      </div>
      {changed && !isNew && <div className="hint mt6">Изменения пресета действуют на новые генерации. Чтобы пересобрать кадры товаров по новому плану — сохраните и нажмите «Применить к товарам».</div>}
    </div>
  );
}

function BlockModel({ label, tip, value, models, baseModel, resolution, stats, onChange }: {
  label: string; tip: string; value: string; models: CatalogModel[] | null; baseModel: string; resolution: string;
  stats: PresetListing["model_stats"]; onChange: (v: string) => void;
}) {
  return (
    <>
      <label className="form-label">{label}</label>
      <div>
        <ModelSelect value={value} onChange={onChange} models={models} emptyLabel="основная" fallback={baseModel} baseModel={baseModel}
          resolution={resolution} />
        <div className="hint mt4">{tip}
          {stats.length > 0 && <> · по вашим кадрам: {stats.map((x) => `${x.model.split("/").pop()} — ${x.n} кадр., `
            + `${x.first_pass == null ? "без проверки" : x.first_pass + "% с 1-й попытки"}, ${x.avg_cost} ₽`).join("; ")}</>}
        </div>
      </div>
    </>
  );
}

function PlanRow({ label, hint, max, value, onChange }: { label: string; hint: string; max: number; value: number; onChange: (v: number) => void }) {
  return (
    <>
      <label className="form-label">{label}</label>
      <div className="plan-row">
        <button onClick={() => onChange(Math.max(0, value - 1))} disabled={value <= 0}>−</button>
        <b className="plan-n">{value}</b>
        <button onClick={() => onChange(Math.min(max, value + 1))} disabled={value >= max}>＋</button>
        <span className="hint">{hint}</span>
      </div>
    </>
  );
}
