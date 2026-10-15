import type { Dialogs } from "../App";
import { assetUrl } from "../api/client";
import type { Product } from "../api/types";
import { useActions } from "../hooks/useActions";
import { useProject } from "../ProjectContext";
import { FrameTile } from "./FrameTile";
import { useUI } from "./ui";

const VIEW_RU: Record<string, string> = {
  front: "спереди", back: "сзади", "outer side": "внешняя сторона", "inner side": "внутренняя сторона", side: "сбоку",
  "three-quarter front": "¾ спереди", "three-quarter back": "¾ сзади", top: "сверху", sole: "подошва",
  detail: "деталь", pair: "пара", worn: "на человеке", packaging: "упаковка",
};

export function ProductCard({ product: p, dialogs }: { product: Product; dialogs: Dialogs }) {
  const { api, reload, run, selected, toggleSelected, state, pickedFrames, togglePicked } = useProject();
  const { generate, regenerate, profiles } = useActions();
  const ui = useUI();
  const chosen = p.photos.filter((x) => x.selected);
  const busy = p.profile_job?.state === "running";
  const own = p.preset_id ? state.presets.find((x) => x.id === p.preset_id) : null;

  const toggleRef = (asset: string) =>
    run(async () => {
      const next = p.photos.filter((x) => (x.asset === asset ? !x.selected : x.selected)).map((x) => x.asset);
      await api.setRefs(p.id, next);
      await reload();
    });

  const profileClick = async () => {
    if (p.profile) {
      dialogs.openProfile(p.id);
      return;
    }
    if (await ui.confirm({ text: `Составить профиль товара «${p.sku}» по фото? Текущие промпты кадров не изменятся.`, ok: "Составить" })) {
      profiles([p.id], false);
    }
  };

  return (
    <section className="card">
      <div className="card-h">
        <input type="checkbox" checked={selected.has(p.id)} onChange={(e) => toggleSelected(p.id, e.target.checked)} />
        <b>{p.sku}</b>
        <span className={`cnt ${p.total && p.done === p.total ? "full" : ""}`}>{p.done}/{p.total}</span>
        {busy ? (
          <span className="pbusy">составляю профиль по фото…</span>
        ) : p.profile ? (
          <span className="pchip2" title="Профиль товара — открыть и поправить" onClick={profileClick}>
            🧠 {p.profile.category}{p.profile.subcategory ? ` · ${p.profile.subcategory}` : ""} · {p.profile.summary}
          </span>
        ) : (
          <button title="ИИ составит профиль товара по фото: описание, детали, чек-лист проверки, кадры" onClick={profileClick}>🧠 Профиль</button>
        )}
        {own && <span className="tag preset-tag" title="Свой пресет товара" onClick={dialogs.openPresets}>🎛 {own.name}</span>}
        {p.persona && (
          <span className="tag preset-tag" onClick={dialogs.openPersonas}
            title={p.persona.via === "товар" ? "Модель выбрана в профиле товара" : p.persona.via === "проект" ? "Модель проекта"
              : `Модель по группе «${p.persona.via}»`}>👤 {p.persona.name}</span>
        )}
        <span className="spacer" />
        <button disabled={!chosen.length || busy} title="Привести кадры к пресету и сгенерировать недостающие"
          onClick={() => generate([p.id])}>▶ Сгенерировать</button>
      </div>

      <div className="refs">
        <span className="lbl">Референсы {chosen.length} из {p.photos.length}:</span>
        {p.photos.map((ph) => (
          <button key={ph.asset} className={`ref ${ph.selected ? "on" : ""}`} onClick={() => toggleRef(ph.asset)}
            title={(ph.selected ? "Идёт в генерацию" : "Не используется") + (ph.view ? ` · ракурс: ${VIEW_RU[ph.view] || ph.view}` : "")}>
            <img loading="lazy" src={assetUrl(ph.asset, 160)} alt="" />
          </button>
        ))}
        {!chosen.length && <span className="err-text">не выбрано ни одного фото</span>}
      </div>

      {p.profile_job?.state === "error" && <div className="err-text">Профиль: {p.profile_job.error}</div>}

      {p.total ? (
        <div className="frames">
          {p.frames.map((f) => (
            <FrameTile key={f.id} frame={f} onOpen={() => dialogs.openFrame(p.id, f.id)} onRegen={() => regenerate(p, f)}
              picked={pickedFrames.has(f.id)} onPick={(on) => togglePicked(f.id, on)} />
          ))}
        </div>
      ) : (
        <div className="noprompts">
          Промптов для этого товара нет.
          <div className="row center">
            <button className="primary" disabled={busy || !chosen.length} onClick={() => profiles([p.id], true)}>
              ✨ Составить профиль и промпты по фото
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
