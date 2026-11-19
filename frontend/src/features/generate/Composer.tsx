import { Icon } from "../../layout/Icon";
import { useActions } from "../../hooks/useActions";
import { useProject } from "../../ProjectContext";
import { BATCH } from "./runOptions";
import { useGenerationSelection } from "./GenerationSelection";

export function Composer() {
  const { limit, setLimit } = useProject();
  const { generate } = useActions();
  const { target, setTarget, ids, selectedIds, visibleIds } = useGenerationSelection();
  return (
    <section className="runbar" id="generation-start" aria-label="Запуск съёмки">
      <label className="run-what">
        <small>Что снимать</small>
        <select aria-label="Область обработки" value={target} onChange={e => setTarget(e.target.value as typeof target)}>
          <option value="selected">Выбранные ({selectedIds.length})</option>
          <option value="visible">В списке ({visibleIds.length})</option>
          <option value="project">Весь проект</option>
        </select>
      </label>
      <label className="run-what">
        <small>Количество кадров</small>
        <select aria-label="Ограничение кадров" value={limit} onChange={e => setLimit(+e.target.value)}>
          {!BATCH.some(([key]) => key === limit) && <option value={limit}>До {limit} кадров</option>}
          {BATCH.map(([key, name]) => <option key={key} value={key}>{name}</option>)}
        </select>
      </label>
      <button className="primary big" disabled={!ids.length} onClick={() => void generate([...ids], limit)}>
        <Icon name="spark" size={18} /> {ids.length ? `Сгенерировать (${ids.length} тов.)` : "Сгенерировать"}
      </button>
    </section>
  );
}
