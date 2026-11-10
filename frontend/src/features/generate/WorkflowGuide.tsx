import type { Dialogs } from "../../App";
import { useProject } from "../../ProjectContext";

export function WorkflowGuide({ dialogs }: { dialogs: Dialogs }) {
  const { state } = useProject();
  const planned = state.products.filter(p => p.total > 0).length;
  return <nav className="workflow-guide" aria-label="Этапы съёмки">
    <button onClick={dialogs.openImport}><i>1</i><span>Фото товаров<small>{state.products.length} товаров</small></span></button>
    <button onClick={dialogs.openPresets}><i>2</i><span>Шаблон съёмки<small>{state.preset?.name || (planned ? "Планы товаров" : "Автоматическая съёмка")}</small></span></button>
    <a href="#generation-start" onClick={e => { e.preventDefault(); document.getElementById("generation-start")?.scrollIntoView({ block: "center" }); }}><i>3</i><span>Генерация<small>{state.runner.busy ? "Выполняется" : `${state.totals.done} кадров готово`}</small></span></a>
    <a href="#/review"><i>4</i><span>Приёмка<small>{state.totals.review ? `Ждут решения: ${state.totals.review}` : "Проверить результат"}</small></span></a>
  </nav>;
}
