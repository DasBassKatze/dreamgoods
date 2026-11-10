import type { Dialogs } from "../App";
import { useProject } from "../ProjectContext";
import { AdvancedFields } from "../features/interface/InterfaceMode";
import { Icon } from "../layout/Icon";

export function ProjectBar({ dialogs }: { dialogs: Dialogs }) {
  const { state } = useProject();
  const own = state.products.filter(p => p.preset_id && p.preset_id !== state.preset?.id).length;
  return <div className="projectbar">
    <button className="pb-card" onClick={dialogs.openPresets}>
      <span className="pb-ico"><Icon name="presets" size={19} /></span><span className="pb-text"><small>Шаблон съёмки</small>
        <b>{state.preset?.name || "Автоматическая съёмка"}</b><em>{state.preset ? `${state.preset.total} кадров на товар` : "План по фотографиям товара"}{own ? ` · свои настройки у ${own} товаров` : ""}</em></span>
    </button>
    <AdvancedFields title="Образ и стиль" summary={`${state.persona?.name || "Человека подберёт ИИ"} · ${state.style_ref?.name || "Без референса съёмки"}`}>
      <div className="row wrap"><button onClick={dialogs.openPersonas}><Icon name="personas" /> Человек в кадре</button>
        <button onClick={dialogs.openStyles}><Icon name="styles" /> Референс съёмки</button>
        <button onClick={dialogs.openImport}><Icon name="upload" /> Добавить фото</button></div>
    </AdvancedFields>
  </div>;
}
