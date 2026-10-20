import { plural } from "../../lib/format";
import { Icon } from "../../layout/Icon";
import { useActions } from "../../hooks/useActions";
import { useProject } from "../../ProjectContext";
import { BATCH } from "./runOptions";

/** Запуск генерации: сколько кадров и «Сгенерировать». Пожелания, площадка и формат — в пресете. */
export function Composer() {
  const { state, selected, limit, setLimit } = useProject();
  const { generate } = useActions();
  const preset = state.preset;
  const n = selected.size;

  return (
    <section className="runbar">
      <label className="cmp-batch">
        <span className="cmp-label">Что снимать</span>
        <select value={limit} onChange={(e) => setLimit(+e.target.value)}>
          {BATCH.some(([k]) => k === limit) ? null : <option value={limit}>До {limit} кадров</option>}
          {BATCH.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
        </select>
      </label>
      <span className="cmp-scope">
        {n ? <>{n} {plural(n, "выбранный товар", "выбранных товара", "выбранных товаров")}</> : <>все товары проекта</>}
        {preset ? <> · пресет «{preset.name}» · формат {preset.aspect || "3:4"}</> : null}
      </span>
      <button className="primary big" onClick={() => generate(n ? [...selected] : null, limit, {})}>
        <Icon name="spark" size={18} /> Сгенерировать
      </button>
    </section>
  );
}
