import { useState, type DragEvent } from "react";
import { assetUrl } from "../../api/client";
import type { ImportGroup, ImportView, PhotoRole } from "../../api/types";
import { rub } from "../../lib/format";

const ROLE_RU: Record<PhotoRole, string> = { product: "товар", packaging: "упаковка", label: "бирка", junk: "не брать" };
const ROLE_NEXT: Record<PhotoRole, PhotoRole> = { product: "label", packaging: "label", label: "junk", junk: "product" };

interface Props {
  view: ImportView;
  groups: ImportGroup[];
  roles: Record<string, PhotoRole>;
  labelMode: string;
  onGroups: (g: ImportGroup[]) => void;
  onRoles: (r: Record<string, PhotoRole>) => void;
  onBack: () => void;
  onApply: () => void;
  onRestart: () => void;
}

export function GroupsStep({ view, groups, roles, labelMode, onGroups, onRoles, onBack, onApply, onRestart }: Props) {
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());     // выбранные кликом фото — для переноса
  const pick = (n: string) => setPicked((s) => { const x = new Set(s); if (x.has(n)) x.delete(n); else x.add(n); return x; });
  const photo = (n: string) => view.photos.find((p) => p.name === n);
  const real = groups.filter((g) => !g.junk && g.photos.length);
  const labels = Object.values(roles).filter((r) => r === "label").length;

  /** Перенос фото (перетащенного или выбранных кликом) в другой товар, в «не использовать» или в новый товар. */
  const moveTo = (targetId: string, names?: string[]) => {
    const list = names || (drag ? (picked.has(drag) ? [...picked] : [drag]) : []);
    if (!list.length) return;
    let next = groups.map((g) => ({ ...g, photos: g.photos.filter((n) => !list.includes(n)) }));
    let target = next.find((g) => g.id === targetId);
    if (targetId === "__new") {
      const k = next.filter((g) => /^новая_группа/.test(g.name)).length + 1;
      target = { id: `n${Date.now()}`, name: `новая_группа_${k}`, article: "", articles: [], text: "", product: "", photos: [], exists: false };
      const j = next.findIndex((g) => g.junk);
      next = [...next.slice(0, j < 0 ? next.length : j), target, ...next.slice(j < 0 ? next.length : j)];
    }
    if (!target) return;
    target.photos.push(...list);
    onGroups(next);
    const r = { ...roles };
    list.forEach((n) => { if (target!.junk) r[n] = "junk"; else if (r[n] === "junk") r[n] = "product"; });
    onRoles(r);
    setDrag(null);
    setOver(null);
    setPicked(new Set());
  };

  const merge = (fromId: string, intoId: string) => {
    const from = groups.find((g) => g.id === fromId)!;
    onGroups(groups.map((g) =>
      g.id === intoId ? { ...g, photos: [...g.photos, ...from.photos], articles: [...new Set([...g.articles, ...from.articles])] }
        : g.id === fromId ? { ...g, photos: [] } : g));
  };

  const rename = (id: string, name: string) => onGroups(groups.map((g) => (g.id === id ? { ...g, name } : g)));
  const describe = (id: string, description: string) => onGroups(groups.map((g) => (g.id === id ? { ...g, description } : g)));
  const flag = (id: string, sort_error: boolean) => onGroups(groups.map((g) => (g.id === id ? { ...g, sort_error } : g)));
  // все артикулы, которые ИИ прочитал на бирках этой загрузки, — для выбора названия товара
  const allArts = [...new Set(view.photos.map((p) => (p.article || "").trim()).filter(Boolean))].sort();
  const targets = groups.filter((g) => !g.junk && (g.photos.length || g.id.startsWith("n")));

  const dropProps = (id: string) => ({
    onDragOver: (e: DragEvent) => { if (drag) { e.preventDefault(); setOver(id); } },
    onDragLeave: () => setOver((o) => (o === id ? null : o)),
    onDrop: (e: DragEvent) => { e.preventDefault(); moveTo(id); },
  });

  return (
    <>
      <div className="hint mb10">
        Фото: <b>{view.photos.length}</b> · товаров: <b>{real.length}</b> · бирок: <b>{labels}</b>
        {view.cost > 0 && <> · стоимость анализа: <b>{rub(view.cost)}</b></>}
      </div>
      <div className="hint mb10">
        Чтобы перенести фото в другой товар, перетащите его или выберите кликом (можно несколько) и укажите, куда
        перенести. Метка внизу фото меняет роль: товар → бирка → не брать. «Бирка» — отдельное фото этикетки: с неё
        берутся артикул и состав, в генерацию оно не идёт; фото товара с наклеенной биркой (например, подошва) оставьте
        «товаром». Если ИИ разложил неверно — отметьте «ошибка раскладки», это поможет улучшить раскладку.
      </div>
      {picked.size > 0 && (
        <div className="ig-movebar">
          <b>Выбрано фото: {picked.size}</b>
          <select value="" onChange={(e) => e.target.value && moveTo(e.target.value, [...picked])}>
            <option value="">перенести в…</option>
            {targets.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            <option value="__new">новый товар</option>
            {groups.some((g) => g.junk) && <option value="junk">не использовать</option>}
          </select>
          <button onClick={() => setPicked(new Set())}>Снять выбор</button>
        </div>
      )}
      <datalist id="ig-arts">{allArts.map((a) => <option key={a} value={a} />)}</datalist>
      <div className="igroups">
        {groups.filter((g) => g.photos.length || !g.junk).map((g) => {
          const products = g.photos.filter((n) => roles[n] !== "label" && roles[n] !== "junk").length;
          return (
            <div key={g.id} className={`ig ${g.junk ? "junk" : ""} ${over === g.id ? "over" : ""}`} {...dropProps(g.id)}>
              <div className="ig-h">
                {g.junk ? (
                  <><b>Не использовать</b><span className="hint">размытые, случайные и лишние фото — в товары не попадут</span></>
                ) : (
                  <>
                    <input type="text" value={g.name} title="Артикул товара — впишите или выберите из распознанных"
                      list="ig-arts" onChange={(e) => rename(g.id, e.target.value)} />
                    {allArts.length > 0 && (
                      <select className="ig-art" value="" title="Выбрать артикул из прочитанных ИИ на бирках"
                        onChange={(e) => e.target.value && rename(g.id, e.target.value)}>
                        <option value="">артикул из распознанных…</option>
                        {g.articles.length > 0 && <optgroup label="с бирок этого товара">
                          {g.articles.map((a) => <option key={a} value={a}>{a}</option>)}</optgroup>}
                        {allArts.some((a) => !g.articles.includes(a)) && <optgroup label="другие в этой загрузке">
                          {allArts.filter((a) => !g.articles.includes(a)).map((a) => <option key={a} value={a}>{a}</option>)}</optgroup>}
                      </select>
                    )}
                    {g.article ? null
                      : g.photos.some((n) => roles[n] === "label")
                        ? <span className="tag">{labelMode === "read" ? "артикул на бирке не прочитан" : "бирка отмечена"}</span>
                        : <span className="tag bad">бирки нет</span>}
                    {g.exists && <span className="tag">товар уже есть — фото добавятся</span>}
                    {g.warn && <span className="tag warn" title="По правилам раскладки эту группу стоит проверить">⚠ {g.warn}</span>}
                    {(g.articles?.length || 0) > 1 && <span className="tag bad">на бирках разные артикулы: {g.articles.join(", ")} — проверьте</span>}
                    <span className="hint">{g.product}{g.text ? " · " + g.text : ""}</span>
                    <span className="spacer" />
                    <span className="hint">товар: {products}</span>
                    <label className={`check small ig-flag ${g.sort_error ? "on" : ""}`} title="ИИ разложил этот товар неверно: смешал товары, разделил один товар или перепутал бирку">
                      <input type="checkbox" checked={!!g.sort_error} onChange={(e) => flag(g.id, e.target.checked)} /> ошибка раскладки</label>
                    <select value="" onChange={(e) => e.target.value && merge(g.id, e.target.value)}>
                      <option value="">объединить с…</option>
                      {groups.filter((x) => x.id !== g.id && !x.junk && x.photos.length).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                    </select>
                  </>
                )}
              </div>
              <div className="ithumbs">
                {g.photos.map((n) => {
                  const r = roles[n] || "product";
                  const ph = photo(n);
                  return (
                    <div key={n} className={`it ${r} ${drag === n ? "dragging" : ""} ${picked.has(n) ? "picked" : ""}`} draggable
                      onClick={() => pick(n)}
                      onDragStart={(e) => { setDrag(n); e.dataTransfer.effectAllowed = "move"; }}
                      onDragEnd={() => { setDrag(null); setOver(null); }}
                      title={`${n}${ph?.article ? " · артикул " + ph.article : ""}${ph?.text ? " · " + ph.text : ""}`}>
                      {ph && <img loading="lazy" src={assetUrl(ph.asset, 200)} alt="" />}
                      {picked.has(n) && <span className="pk">✓</span>}
                      <span className="rl" onClick={(e) => { e.stopPropagation(); onRoles({ ...roles, [n]: ROLE_NEXT[r] }); }}>
                        {ROLE_RU[r]}
                      </span>
                    </div>
                  );
                })}
              </div>
              {!g.junk && (
                <textarea className="ig-desc" rows={2} maxLength={2000} value={g.description || ""}
                  onChange={(e) => describe(g.id, e.target.value)}
                  placeholder="Описание товара словами (необязательно): что это, материал, цвет, особенности — например, «зимние ботинки из натуральной кожи, мех внутри, молния с внутренней стороны»" />
              )}
            </div>
          );
        })}
        <div className={`ig newg ${over === "__new" ? "over" : ""}`} {...dropProps("__new")}>＋ Перетащите сюда фото, чтобы создать новую группу</div>
      </div>
      <div className="row mt12 import-actions">
        <span className="hint">товаров: <b>{real.length}</b> · фото: <b>{view.photos.length}</b></span>
        <button onClick={onBack}>← Загрузить ещё</button>
        <button onClick={onRestart}>Начать заново</button>
        <span className="spacer" />
        <button className="primary" onClick={onApply}>Создать товары</button>
      </div>
    </>
  );
}
