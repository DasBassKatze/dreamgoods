import { useEffect, useState } from "react";
import type { Preset, PresetApplyResult, PresetListing } from "../../api/types";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";

type Target = "selected" | "categories" | "all";

export function PresetApply({ listing, preset, onBack, onDone, onRefresh }: {
  listing: PresetListing; preset: Preset; onBack: () => void; onDone: () => void; onRefresh: () => Promise<unknown> }) {
  const { api, selected, reload, run } = useProject();
  const ui = useUI();
  const [target, setTarget] = useState<Target>(selected.size ? "selected" : "categories");
  const [cats, setCats] = useState<string[]>([]);
  const [makeDefault, setMakeDefault] = useState(preset.is_default);
  const [preview, setPreview] = useState<PresetApplyResult | null>(null);
  const [detecting, setDetecting] = useState(false);
  const toggle = (name: string, on: boolean) => setCats(on ? [...cats, name] : cats.filter((x) => x !== name));

  // пока ИИ определяет подразделы — обновляем список раз в 2 с
  useEffect(() => {
    if (!detecting) return;
    if (!listing.no_subcategory) { setDetecting(false); return; }
    const t = window.setTimeout(() => onRefresh(), 2000);
    return () => window.clearTimeout(t);
  }, [detecting, listing, onRefresh]);

  const detect = () =>
    run(async () => {
      await api.detectSubcategories();
      setDetecting(true);
      ui.toast("ИИ определяет подразделы…");
    });

  const body = () => ({
    product_ids: target === "selected" ? [...selected] : undefined,
    categories: target === "categories" ? cats : undefined,
    everything: target === "all",
    make_default: makeDefault,
  });

  useEffect(() => {
    let alive = true;
    api.applyPreset(preset.id, { ...body(), dry_run: true }).then((r) => alive && setPreview(r)).catch(() => alive && setPreview(null));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, preset.id, target, cats.join("|"), selected.size, makeDefault]);

  const apply = () =>
    run(async () => {
      if (!preview?.products && !makeDefault) {
        ui.toast("Выберите товары");
        return;
      }
      const ok = await ui.confirm({
        title: `Применить «${preset.name}»`,
        text: <>
          Товаров: {preview?.products ?? 0}. Промпты кадров пересоберутся по плану пресета ({preset.total} кадр.).
          <p className="hint">Сразу и бесплатно: {preview?.instant ?? 0}. ИИ заново составит профиль (в нём не хватает нужных видов кадров,
            ≈ 0,04 ₽ за товар): {preview?.need_profile ?? 0}.</p>
          <p className="hint">Уже сгенерированные кадры, у которых изменится задание, уйдут в историю (не удаляются) и будут сгенерированы заново при запуске.</p>
        </>,
        ok: "Применить",
      });
      if (!ok) return;
      const r = await api.applyPreset(preset.id, { ...body(), rebuild: true });
      ui.toast(`Готово: товаров ${r.products}, пересобрано ${r.rebuilt ?? 0}, профилей ИИ ${r.queued ?? 0}`, 5000);
      await reload();
      onDone();
    });

  return (
    <div>
      <div className="row mb10"><button onClick={onBack}>← К пресету</button><b>Применить «{preset.name}»</b></div>
      <div className="form grid">
        <label className="form-label">Каким товарам</label>
        <div className="ch-col">
          <label className="check"><input type="radio" checked={target === "selected"} disabled={!selected.size} onChange={() => setTarget("selected")} />
            {" "}выбранным в списке ({selected.size}){!selected.size && <span className="hint"> — отметьте товары галочками на главном экране</span>}</label>
          <label className="check"><input type="radio" checked={target === "categories"} onChange={() => setTarget("categories")} /> по категориям:</label>
          {target === "categories" && (
            <div className="cat-tree">
              {listing.categories.map((c) => (
                <div key={c.name} className="cat-group">
                  <label className={`pchip ${cats.includes(c.name) ? "cur" : ""}`}>
                    <input type="checkbox" checked={cats.includes(c.name)} onChange={(e) => toggle(c.name, e.target.checked)} /> <b>{c.name}</b> · {c.count}
                  </label>
                  {!cats.includes(c.name) && c.subs.length > 0 && (
                    <div className="row cat-subs">
                      {c.subs.map((sc) => {
                        const key = `${c.name} / ${sc.name}`;
                        return (
                          <label key={key} className={`pchip ${cats.includes(key) ? "cur" : ""}`}>
                            <input type="checkbox" checked={cats.includes(key)} onChange={(e) => toggle(key, e.target.checked)} /> {sc.name} · {sc.count}
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
              {listing.no_subcategory > 0 && (
                <div className="row">
                  <span className="hint">У {listing.no_subcategory} товаров нет подраздела (профиль составлен раньше).</span>
                  <button disabled={detecting} onClick={detect}>{detecting ? "Определяю…" : "🗂 Определить подразделы ИИ"}</button>
                  <span className="hint">один текстовый запрос, копейки</span>
                </div>
              )}
            </div>
          )}
          <label className="check"><input type="radio" checked={target === "all"} onChange={() => setTarget("all")} /> всем товарам проекта</label>
        </div>
        <label className="form-label">Для новых товаров</label>
        <label className="check"><input type="checkbox" checked={makeDefault} onChange={(e) => setMakeDefault(e.target.checked)} /> сделать пресетом проекта
          (его получат товары без своего пресета и новые товары после импорта)</label>
        <label className="form-label">Что произойдёт</label>
        <div className="hint">{preview ? <>товаров: <b>{preview.products}</b> · пересоберутся сразу: <b>{preview.instant}</b> ·
          нужен новый профиль ИИ: <b>{preview.need_profile}</b></> : "…"}</div>
      </div>
      <div className="row mt16"><span className="spacer" /><button onClick={onBack}>Отмена</button>
        <button className="primary" onClick={apply}>Применить</button></div>
    </div>
  );
}
