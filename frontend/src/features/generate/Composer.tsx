import { ASPECTS, plural } from "../../lib/format";
import { Icon } from "../../layout/Icon";
import { useActions, type RunOptions } from "../../hooks/useActions";
import { useProject } from "../../ProjectContext";
import { ASPECT_PILLS, BATCH, MARKET_PILLS } from "./runOptions";

interface Props {
  value: RunOptions;
  onChange: (v: RunOptions) => void;
}

/** Строка запуска: пожелания текстом, площадка, формат, сколько кадров — и «Сгенерировать». */
export function Composer({ value: v, onChange }: Props) {
  const { state, selected, limit, setLimit } = useProject();
  const { generate } = useActions();
  const set = (patch: RunOptions) => onChange({ ...v, ...patch });
  const preset = state.preset;
  const marketAspect = MARKET_PILLS.find(([k]) => k === v.market)?.[2] || "";
  const presetAspect = preset?.aspect || "3:4";
  const effAspect = v.aspect || marketAspect || presetAspect;
  const n = selected.size;
  const extraAspect = v.aspect && !ASPECT_PILLS.includes(v.aspect);

  return (
    <section className="composer">
      <div className="cmp-input">
        <span className="cmp-spark"><Icon name="spark" size={20} /></span>
        <textarea rows={2} maxLength={1500} value={v.brief || ""} onChange={(e) => set({ brief: e.target.value })}
          placeholder="Опишите ваш товар и желаемый стиль… Например: «тёплый осенний свет, бежевый фон, акцент на замше»" />
        {v.brief ? <button className="cmp-clear" title="Очистить" onClick={() => set({ brief: "" })}>×</button> : null}
      </div>
      <div className="cmp-row">
        <div className="cmp-field">
          <span className="cmp-label">Маркетплейс</span>
          <div className="pills">
            {MARKET_PILLS.map(([k, name]) => (
              <button key={k || "preset"} className={(v.market || "") === k ? "on" : ""} onClick={() => set({ market: k })}
                title={k ? `Обложка и формат по правилам ${name}` : `Как в пресете${preset?.market_name ? `: ${preset.market_name}` : ""}`}>
                {name}
              </button>
            ))}
          </div>
        </div>
        <div className="cmp-field">
          <span className="cmp-label">Соотношение сторон</span>
          <div className="pills">
            {ASPECT_PILLS.map((a) => (
              <button key={a || "auto"} className={(v.aspect || "") === a ? "on" : ""} onClick={() => set({ aspect: a })}
                title={a ? ASPECTS.find(([k]) => k === a)?.[1] : `Авто: ${marketAspect || presetAspect}`}>
                {a || "Авто"}
              </button>
            ))}
            <select className={`pill-select ${extraAspect ? "on" : ""}`} value={extraAspect ? v.aspect : ""}
              onChange={(e) => set({ aspect: e.target.value })} title="Другие форматы">
              <option value="">ещё…</option>
              {ASPECTS.filter(([k]) => !ASPECT_PILLS.includes(k)).map(([k, name]) => <option key={k} value={k}>{name}</option>)}
            </select>
          </div>
        </div>
      </div>
      <div className="cmp-foot">
        <label className="cmp-batch">
          <span className="cmp-label">Пакетная генерация</span>
          <select value={limit} onChange={(e) => setLimit(+e.target.value)}>
            {BATCH.some(([k]) => k === limit) ? null : <option value={limit}>До {limit} кадров</option>}
            {BATCH.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
          </select>
        </label>
        <span className="cmp-scope">
          {n ? <>{n} {plural(n, "выбранный товар", "выбранных товара", "выбранных товаров")}</> : <>все товары проекта</>}
          {" · "}формат {effAspect}{preset ? <> · пресет «{preset.name}»</> : null}
        </span>
        <span className="spacer" />
        <button className="primary big" onClick={() => generate(n ? [...selected] : null, limit, v)}>
          <Icon name="spark" size={18} /> Сгенерировать
        </button>
      </div>
    </section>
  );
}
