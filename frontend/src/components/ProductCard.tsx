import { AdvancedFields } from "../features/interface/InterfaceMode";
import { useDeleteProducts } from "../hooks/useDeleteProducts";
import type { Dialogs } from "../App";
import { assetUrl } from "../api/client";
import type { Product } from "../api/types";
import { useActions } from "../hooks/useActions";
import { useProject } from "../ProjectContext";
import { SHORT_MARKET, useRunOptions } from "../features/generate/runOptions";
import { pad } from "../lib/format";
import { Icon } from "../layout/Icon";
import { FrameTile } from "./FrameTile";
import { ProductSettings } from "./ProductSettings";
import { useUI } from "./ui";

const VIEW_RU: Record<string, string> = {
  front: "спереди", back: "сзади", "outer side": "внешняя сторона", "inner side": "внутренняя сторона", side: "сбоку",
  "three-quarter front": "¾ спереди", "three-quarter back": "¾ сзади", top: "сверху", sole: "подошва",
  detail: "деталь", pair: "пара", worn: "на человеке", packaging: "упаковка",
};

interface Props {
  product: Product;
  dialogs: Dialogs;
  focus: number | null;
  onFocus: (productId: number, frameId: number) => void;
}

export function ProductCard({ product: p, dialogs, focus, onFocus }: Props) {
  const { api, reload, run, selected, toggleSelected, state, pickedFrames, togglePicked } = useProject();
  const { generate, regenerate, profiles, quick } = useActions();
  const opts = useRunOptions();
  const remove = useDeleteProducts();
  const ui = useUI();
  const zoomRefs = (i: number) => ui.zoom(p.photos.map((x) => ({ asset: x.asset,
    caption: `${p.sku}${x.view ? ` · ${VIEW_RU[x.view] || x.view}` : ""} · ${x.selected ? "идёт в генерацию" : "не используется"}` })), i);
  const chosen = p.photos.filter((x) => x.selected);
  const busy = p.profile_job?.state === "running";
  const own = p.preset_id ? state.presets.find((x) => x.id === p.preset_id) : null;
  const eff = own || state.preset;
  const aspect = eff?.aspect || "3:4";
  const label = [eff?.market && eff.market !== "none" ? SHORT_MARKET[eff.market] : "", aspect].filter(Boolean).join(" · ");

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
    <section className="card" data-product-id={p.id}>
      <div className="card-h">
        <input type="checkbox" aria-label={`Выбрать товар ${p.sku}`} checked={selected.has(p.id)} onChange={(e) => toggleSelected(p.id, e.target.checked)} />
        <b>{p.sku}</b>
        <span className={`cnt ${p.total && p.done === p.total ? "full" : ""}`}>{p.done}/{p.total}</span>
        {busy ? (
          <span className="pbusy">составляю профиль по фото…</span>
        ) : p.profile ? (
          <button className="pchip2" title="Профиль товара — открыть и поправить" onClick={profileClick}>
            <Icon name="spark" size={13} />{p.profile.category}{p.profile.subcategory ? ` · ${p.profile.subcategory}` : ""} · {p.profile.summary}
          </button>
        ) : (
          <button title="ИИ составит профиль товара по фото: описание, детали, чек-лист проверки, кадры" onClick={profileClick}><Icon name="spark" size={14} /> Описание по фото · платно</button>
        )}
        <span className="mk-chip" title="Площадка и формат по пресету товара">{label}</span>
        <span className="spacer" />
        <button className="danger" aria-label={`Удалить товар ${p.sku}`} onClick={() => void remove([p.id])}>Удалить товар</button>
        <button disabled={!chosen.length || busy} title="Привести кадры к пресету и сгенерировать недостающие (с пожеланиями из строки запуска)"
          onClick={() => generate([p.id], 0, opts)}>Сгенерировать</button>
      </div>

      <AdvancedFields title="Настройки товара" summary={`${p.preset_id || p.persona_id || p.style_ref_id ? "Используются ваши настройки" : "Из проекта"} · ${eff?.name || "Автоматическая съёмка"}`}>
        <ProductSettings product={p} dialogs={dialogs} />
      </AdvancedFields>

      <div className="refs">
        <span className="lbl">Исходные фото · выбрано {chosen.length} из {p.photos.length}:</span>
        {p.photos.map((ph, i) => (
          <div key={ph.asset} className="ref-entry"><button className={`ref ${ph.selected ? "on" : ""}`} onClick={() => toggleRef(ph.asset)}
            aria-pressed={ph.selected} aria-label={`Фото ${i + 1} товара ${p.sku}: ${ph.selected ? "используется" : "не используется"}`}
            title={(ph.selected ? "Идёт в генерацию" : "Не используется") + (ph.view ? ` · ракурс: ${VIEW_RU[ph.view] || ph.view}` : "")}>
            <img loading="lazy" src={assetUrl(ph.asset, 160)} alt="" />
          </button><button className="ref-zoom" aria-label={`Открыть фото ${i + 1} товара ${p.sku}`} onClick={() => zoomRefs(i)}><Icon name="search" size={14} /></button></div>
        ))}
        {!chosen.length && <span className="err-text">не выбрано ни одного фото</span>}
      </div>

      {p.profile_job?.state === "error" && <div className="err-text">Профиль: {p.profile_job.error}</div>}

      {p.total ? (
        <div className="frames">
          {p.frames.map((f) => (
            <FrameTile key={f.id} frame={f} fileName={`${p.sku}_${pad(f.i)}`} aspect={aspect} label={label}
              focused={focus === f.id} onFocus={() => onFocus(p.id, f.id)} onUpscale={() => quick(p, f, "upscale")}
              onOpen={() => dialogs.openFrame(p.id, f.id)} onRegen={() => regenerate(p, f)}
              picked={pickedFrames.has(f.id)} onPick={(on) => togglePicked(f.id, on)} />
          ))}
        </div>
      ) : (
        <div className="noprompts">
          План кадров ещё не подготовлен.
          <div className="row center">
            <button className="primary" disabled={busy || !chosen.length} onClick={() => profiles([p.id], true)}>
              Подготовить план по фото · платно
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
