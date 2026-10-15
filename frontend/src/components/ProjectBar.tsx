import type { Dialogs } from "../App";
import { assetUrl } from "../api/client";
import { useProject } from "../ProjectContext";
import { Icon } from "../layout/Icon";

/** Настройки съёмки проекта: пресет, оформление, модель клиента. Нейросеть генерации выбирается в пресете. */
export function ProjectBar({ dialogs }: { dialogs: Dialogs }) {
  const { state } = useProject();
  return (
    <div className="projectbar">
      <button className="pb-card upload" onClick={dialogs.openImport} title="Загрузить фото товаров — сервис сам разложит их по артикулам">
        <span className="pb-ico"><Icon name="upload" size={20} /></span>
        <span className="pb-text"><small>Фото товаров</small><b>Загрузить фото</b><em>{state.products.length} товар(ов) в проекте</em></span>
      </button>
      <button className="pb-card" onClick={dialogs.openPresets} title="Пресет генерации проекта: качество, площадка и план кадров">
        <span className="pb-ico"><Icon name="presets" size={20} /></span>
        <span className="pb-text"><small>Пресет</small>
          <b>{state.preset ? state.preset.name : "не выбран"}</b>
          {state.preset && <em>{state.preset.total} кадр. на товар{state.preset.plan_mode === "manual" ? " · свои методы" : ""}</em>}
        </span>
      </button>
      <button className="pb-card" onClick={dialogs.openStyles} title="Референс оформления: пример стиля съёмки для кадров">
        {state.style_ref?.asset ? <img src={assetUrl(state.style_ref.asset, 96)} alt="" /> : <span className="pb-ico"><Icon name="styles" size={20} /></span>}
        <span className="pb-text"><small>Оформление</small><b>{state.style_ref ? state.style_ref.name : "не задано"}</b></span>
      </button>
      <button className="pb-card" onClick={dialogs.openPersonas} title="Модели клиента: человек на кадрах в использовании и общих планах">
        {state.persona?.asset ? <img src={assetUrl(state.persona.asset, 96)} alt="" /> : <span className="pb-ico"><Icon name="personas" size={20} /></span>}
        <span className="pb-text"><small>Модель</small><b>{state.persona ? state.persona.name : "подбирает ИИ"}</b></span>
      </button>
    </div>
  );
}
