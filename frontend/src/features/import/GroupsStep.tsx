import { useState, type DragEvent } from "react";
import { assetUrl } from "../../api/client";
import type { ImportGroup, ImportView, PhotoRole } from "../../api/types";
import { rub } from "../../lib/format";

const ROLE_RU: Record<PhotoRole, string> = { product: "товар", packaging: "упаковка", label: "этикетка", junk: "не брать" };
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
}

export function GroupsStep({ view, groups, roles, labelMode, onGroups, onRoles, onBack, onApply }: Props) {
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const photo = (n: string) => view.photos.find((p) => p.name === n);
  const real = groups.filter((g) => !g.junk && g.photos.length);
  const labels = Object.values(roles).filter((r) => r === "label").length;

  const moveTo = (targetId: string) => {
    if (!drag) return;
    let next = groups.map((g) => ({ ...g, photos: g.photos.filter((n) => n !== drag) }));
    let target = next.find((g) => g.id === targetId);
    if (targetId === "__new") {
      const k = next.filter((g) => /^новая_группа/.test(g.name)).length + 1;
      target = { id: `n${Date.now()}`, name: `новая_группа_${k}`, article: "", articles: [], text: "", product: "", photos: [], exists: false };
      const j = next.findIndex((g) => g.junk);
      next = [...next.slice(0, j < 0 ? next.length : j), target, ...next.slice(j < 0 ? next.length : j)];
    }
    if (!target) return;
    target.photos.push(drag);
    onGroups(next);
    if (target.junk) onRoles({ ...roles, [drag]: "junk" });
    else if (roles[drag] === "junk") onRoles({ ...roles, [drag]: "product" });
    setDrag(null);
    setOver(null);
  };

  const merge = (fromId: string, intoId: string) => {
    const from = groups.find((g) => g.id === fromId)!;
    onGroups(groups.map((g) =>
      g.id === intoId ? { ...g, photos: [...g.photos, ...from.photos], articles: [...new Set([...g.articles, ...from.articles])] }
        : g.id === fromId ? { ...g, photos: [] } : g));
  };

  const rename = (id: string, name: string) => onGroups(groups.map((g) => (g.id === id ? { ...g, name } : g)));

  const dropProps = (id: string) => ({
    onDragOver: (e: DragEvent) => { if (drag) { e.preventDefault(); setOver(id); } },
    onDragLeave: () => setOver((o) => (o === id ? null : o)),
    onDrop: (e: DragEvent) => { e.preventDefault(); moveTo(id); },
  });

  return (
    <>
      <div className="hint mb10">
        Фото: <b>{view.photos.length}</b> · групп: <b>{real.length}</b> · этикеток: <b>{labels}</b> · стоимость анализа: <b>{rub(view.cost)}</b>
      </div>
      <div className="hint mb10">
        Перетаскивайте фото между группами, клик по метке внизу фото меняет роль (товар → этикетка → не использовать). Название группы = артикул товара.
      </div>
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
                    <input type="text" value={g.name} title="Артикул товара" onChange={(e) => rename(g.id, e.target.value)} />
                    {g.article ? <span className="tag">артикул с этикетки: {g.articles.join(", ")}</span>
                      : g.photos.some((n) => roles[n] === "label") ? <span className="tag bad">артикул на этикетке не прочитан</span>
                        : <span className="tag bad">этикетки нет</span>}
                    {g.exists && <span className="tag">товар уже есть — фото добавятся</span>}
                    <span className="hint">{g.product}{g.text ? " · " + g.text : ""}</span>
                    <span className="spacer" />
                    <span className="hint">товар: {products}</span>
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
                    <div key={n} className={`it ${r} ${drag === n ? "dragging" : ""}`} draggable
                      onDragStart={(e) => { setDrag(n); e.dataTransfer.effectAllowed = "move"; }}
                      onDragEnd={() => { setDrag(null); setOver(null); }}
                      title={`${n}${ph?.article ? " · артикул " + ph.article : ""}${ph?.text ? " · " + ph.text : ""}`}>
                      {ph && <img loading="lazy" src={assetUrl(ph.asset, 200)} alt="" />}
                      <span className="rl" onClick={() => onRoles({ ...roles, [n]: ROLE_NEXT[r] })}>
                        {ROLE_RU[r]}{r === "label" && labelMode === "keep" ? "*" : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className={`ig newg ${over === "__new" ? "over" : ""}`} {...dropProps("__new")}>＋ Перетащите сюда фото, чтобы создать новую группу</div>
      </div>
      <div className="row mt12">
        <button onClick={onBack}>← Загрузить ещё / заново</button>
        <span className="spacer" />
        <button className="primary" onClick={onApply}>Создать товары</button>
      </div>
    </>
  );
}
