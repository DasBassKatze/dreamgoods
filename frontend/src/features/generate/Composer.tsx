import type { Dialogs } from "../../App";
import { ProjectBar } from "../../components/ProjectBar";
import { QualityTools, QualitySwitches } from "../../components/Toolbar";
import { Icon } from "../../layout/Icon";
import { useActions } from "../../hooks/useActions";
import { useProject } from "../../ProjectContext";
import { AdvancedFields } from "../interface/InterfaceMode";
import { needsReview } from "../../lib/format";
import { useInterfaceMode } from "../interface/InterfaceMode";
import { BATCH } from "./runOptions";
import { useGenerationSelection } from "./GenerationSelection";

export function Composer({ dialogs }: { dialogs: Dialogs }) {
  const { state, limit, setLimit } = useProject();
  const { generate } = useActions();
  const { target, setTarget, ids, selectedIds, visibleIds, hidden, label } = useGenerationSelection();
  const s = state.settings;
  const { advanced } = useInterfaceMode();
  const targets = state.products.filter(p => ids.includes(p.id));
  const ready = targets.length > 0 && targets.every(p => p.frames.length > 0 && p.frames.every(f => !!f.asset && f.state === "done"));
  const review = targets.some(p => p.frames.some(needsReview));
  return <section className="runbar" id="generation-start" aria-label="Запуск съёмки">
    <div className="run-controls">
      <label className="run-what"><small>Какие товары обработать</small>
        <select aria-label="Область обработки" value={target} onChange={e => setTarget(e.target.value as typeof target)}>
          <option value="selected">Выбранные ({selectedIds.length})</option>
          <option value="visible">В списке ({visibleIds.length})</option>
          <option value="project">Весь проект ({state.products.length})</option>
        </select>
      </label>
      <span className="run-target" aria-live="polite">{label}{target === "selected" && hidden > 0 && <strong>Из них скрыто фильтром: {hidden}</strong>}</span>
      {!advanced && ready && !state.runner.busy ? <button className="primary big" onClick={() => { window.location.hash = review ? "/review" : "/gallery"; }}>
        <Icon name={review ? "search" : "image"} size={18} />{review ? "Проверить результат" : "Открыть галерею"}
      </button> : <button className="primary big" disabled={!ids.length || (!advanced && state.runner.busy)} onClick={() => void generate([...ids], limit, {})}>
        <Icon name="spark" size={18} />{!advanced && state.runner.busy ? "Генерация идёт…" : `Сгенерировать${ids.length ? ` (${ids.length} тов.)` : ""}`}
      </button>}
    </div>
    <QualitySwitches />
    <div className="run-quality">
      <span>{s.qc_enabled && s.qc_autoregen && s.qc_retries > 0 ? `Автопеределка до ${s.qc_retries} раз · платно` : "Без автоматических переделок"}</span>
      <span>Стоимость и бюджет — перед запуском</span></div>
    <AdvancedFields title="Настройки съёмки" summary={`${limit ? `До ${limit} кадров` : "Все недостающие кадры"} · ${state.persona?.name || "Человек: автоматически"} · ${state.style_ref?.name || "Без референса съёмки"}`}>
      <label className="run-what">Количество кадров за запуск
        <select aria-label="Ограничение кадров" value={limit} onChange={e => setLimit(+e.target.value)}>
          {!BATCH.some(([k]) => k === limit) && <option value={limit}>До {limit} кадров</option>}
          {BATCH.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
        </select>
      </label>
      <ProjectBar dialogs={dialogs} />
      <QualityTools />
    </AdvancedFields>
  </section>;
}
