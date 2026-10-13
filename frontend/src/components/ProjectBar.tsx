import type { Dialogs } from "../App";
import { assetUrl } from "../api/client";
import { useProject } from "../ProjectContext";

/** Настройки съёмки проекта: пресет, оформление, модель — три карточки вместо россыпи «чипов». */
export function ProjectBar({ dialogs }: { dialogs: Dialogs }) {
  const { state } = useProject();
  const s = state.settings;
  return (
    <div className="projectbar">
            <button className="pb-card" onClick={dialogs.openPresets} title="Пресет генерации проекта: качество, площадка и план кадров">
        <span className="pb-ico">🎛</span>
        <span className="pb-text"><small>Пресет</small>
          <b>{state.preset ? state.preset.name : "не выбран"}</b>
          {state.preset && <em>{state.preset.total} кадр. на товар{state.preset.plan_mode === "manual" ? " · свои методы" : ""}</em>}
        </span>
      </button>
      <button className="pb-card" onClick={dialogs.openStyles} title="Референс оформления: пример стиля съёмки для кадров">
        {state.style_ref?.asset ? <img src={assetUrl(state.style_ref.asset, 96)} alt="" /> : <span className="pb-ico">🎨</span>}
        <span className="pb-text"><small>Оформление</small><b>{state.style_ref ? state.style_ref.name : "не задано"}</b></span>
      </button>
      <button className="pb-card" onClick={dialogs.openPersonas} title="Модели клиента: человек на кадрах в использовании и общих планах">
        {state.persona?.asset ? <img src={assetUrl(state.persona.asset, 96)} alt="" /> : <span className="pb-ico">👤</span>}
        <span className="pb-text"><small>Модель</small><b>{state.persona ? state.persona.name : "подбирает ИИ"}</b></span>
      </button>
      {state.admin && (
        <button className="pb-card admin-only" onClick={() => dialogs.openCatalog("image")} title="Модель генерации (видно только администратору)">
          <span className="pb-ico">🧠</span>
          <span className="pb-text"><small>Генератор</small><b>{s.model.split("/").pop()}</b><em>{s.resolution} · {s.aspect}</em></span>
        </button>
      )}
    </div>
  );
}
