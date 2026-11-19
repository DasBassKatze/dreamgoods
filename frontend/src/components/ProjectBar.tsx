import type { Dialogs } from "../App";
import { Icon } from "../layout/Icon";
import { useProject } from "../ProjectContext";

export function ProjectBar({ dialogs }: { dialogs: Dialogs }) {
  const { state } = useProject();
  return <div className="row wrap project-look-tools" role="group" aria-label="Настройки проекта">
    {!state.open_import && <button onClick={dialogs.openImport}><Icon name="upload" size={16} /> Добавить фото</button>}
    <button onClick={dialogs.openPresets}><Icon name="presets" size={16} /> Шаблоны съёмки</button>
    <button onClick={dialogs.openPersonas}><Icon name="personas" size={16} /> Человек в кадре</button>
    <button onClick={dialogs.openStyles}><Icon name="styles" size={16} /> Референсы съёмки</button>
  </div>;
}
