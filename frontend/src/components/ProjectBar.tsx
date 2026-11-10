import type { Dialogs } from "../App";
import { Icon } from "../layout/Icon";

export function ProjectBar({ dialogs }: { dialogs: Dialogs }) {
  return <div className="project-look-tools">
    <p className="hint">Образ и стиль — необязательно. Если ничего не выбирать, съёмку подготовит ИИ.</p>
    <div className="row wrap"><button onClick={dialogs.openPersonas}><Icon name="personas" /> Человек в кадре</button>
      <button onClick={dialogs.openStyles}><Icon name="styles" /> Референс съёмки</button>
      <button onClick={dialogs.openPresets}><Icon name="presets" /> Шаблон съёмки</button>
      <button onClick={dialogs.openImport}><Icon name="upload" /> Добавить фото</button></div>
  </div>;
}
