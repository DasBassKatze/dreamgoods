import type { PersonaGroupTree } from "../../api/types";

/** Для каких групп товаров эта модель: категории целиком или отдельные подразделы. */
export function PersonaGroups({ tree, value, conflicts, ownName, onChange }: {
  tree: PersonaGroupTree[]; value: string[]; conflicts: Record<string, string[]>; ownName: string; onChange: (v: string[]) => void;
}) {
  const toggle = (key: string, on: boolean) => onChange(on ? [...value, key] : value.filter((x) => x !== key));
  const other = (key: string) => (conflicts[key] || []).filter((n) => n !== ownName);
  if (!tree.length) return <div className="hint">Товаров в проекте пока нет — группы появятся после импорта.</div>;
  return (
    <div className="cat-tree">
      {tree.map((c) => (
        <div key={c.name} className="cat-group">
          <label className={`pchip ${value.includes(c.name) ? "cur" : ""}`}>
            <input type="checkbox" checked={value.includes(c.name)} onChange={(e) => toggle(c.name, e.target.checked)} />{" "}
            <b>{c.name}</b> · {c.count}
            {other(c.name).length > 0 && <span className="bad-text"> · ещё у «{other(c.name).join("», «")}»</span>}
          </label>
          {c.subs.length > 0 && (
            <div className="row cat-subs">
              {c.subs.map((sc) => {
                const key = `${c.name} / ${sc.name}`;
                return (
                  <label key={key} className={`pchip ${value.includes(key) ? "cur" : ""}`}>
                    <input type="checkbox" checked={value.includes(key)} onChange={(e) => toggle(key, e.target.checked)} /> {sc.name} · {sc.count}
                    {other(key).length > 0 && <span className="bad-text"> · ещё у «{other(key).join("», «")}»</span>}
                  </label>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
