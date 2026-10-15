import type { Dialogs } from "../App";
import type { Product } from "../api/types";
import { useProject } from "../ProjectContext";
import { Icon } from "../layout/Icon";

const QUALITY_RU: Record<string, string> = { draft: "черновик", standard: "стандарт", premium: "премиум", custom: "своё качество" };

/** Настройки генерации товара: пресет, модель и оформление — свои или как в проекте. */
export function ProductSettings({ product: p, dialogs }: { product: Product; dialogs: Dialogs }) {
  const { state, api, reload, run } = useProject();
  const own = p.preset_id ? state.presets.find((x) => x.id === p.preset_id) : null;
  const eff = own || state.preset;
  const personas = state.options?.personas || [];
  const styles = state.options?.styles || [];

  const setPreset = (id: number) =>
    run(async () => {
      // только назначаем — кадры приведутся к пресету при «Сгенерировать»
      await api.applyPreset(id, { product_ids: [p.id], rebuild: false });
      await reload();
    });
  const setPersona = (id: number) => run(async () => { await api.setProductPersona(p.id, id || null); await reload(); });
  const setStyle = (id: number) => run(async () => { await api.setProductStyle(p.id, id || null); await reload(); });

  const viaPersona = p.persona && p.persona_id == null
    ? (p.persona.via === "проект" ? `как в проекте (${p.persona.name})` : `по группе: ${p.persona.name}`)
    : state.persona ? `как в проекте (${state.persona.name})` : "подбирает ИИ";
  const projStyle = state.style_ref ? `как в проекте (${state.style_ref.name})` : "без оформления";

  return (
    <div className="psettings">
      <label className={`ps-field ${own ? "own" : ""}`} title="Пресет товара: качество, площадка, формат и план кадров">
        <span><Icon name="presets" size={14} /> Пресет</span>
        <select value={p.preset_id || 0} onChange={(e) => setPreset(+e.target.value)}>
          <option value={0}>{state.preset ? `как в проекте (${state.preset.name})` : "не выбран"}</option>
          {state.presets.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      </label>
      <label className={`ps-field ${p.persona_id ? "own" : ""}`} title="Модель клиента на кадрах с человеком">
        <span><Icon name="personas" size={14} /> Модель</span>
        <select value={p.persona_id || 0} onChange={(e) => setPersona(+e.target.value)}>
          <option value={0}>{viaPersona}</option>
          {personas.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      </label>
      <label className={`ps-field ${p.style_ref_id ? "own" : ""}`} title="Референс оформления: свет, цвет, фон и настроение кадров">
        <span><Icon name="styles" size={14} /> Оформление</span>
        <select value={p.style_ref_id || 0} onChange={(e) => setStyle(+e.target.value)}>
          <option value={0}>{projStyle}</option>
          {styles.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      </label>
      <span className="ps-sum" title="Что получится по этому пресету">
        {eff ? <>{eff.market_name || "без площадки"} · {eff.aspect || "3:4"} · {QUALITY_RU[eff.quality] || eff.quality} · {eff.total} кадр.</>
          : "пресет не выбран — кадры по профилю товара"}
      </span>
      <button className="link" onClick={dialogs.openPresets}>настроить пресеты</button>
    </div>
  );
}
