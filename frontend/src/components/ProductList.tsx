import type { Dialogs } from "../App";
import type { Product } from "../api/types";
import { qcStatus } from "../lib/format";
import { useProject } from "../ProjectContext";
import { ProductCard } from "./ProductCard";
import type { Filter } from "./Toolbar";

export function matchesFilter(p: Product, filter: Filter) {
  switch (filter) {
    case "todo":
      return p.done < p.total;
    case "err":
      return p.frames.some((f) => f.state === "error");
    case "review":
      return p.frames.some((f) => qcStatus(f) === "review");
    default:
      return true;
  }
}

export function matchesQuery(p: Product, q: string) {
  if (!q) return true;
  const hay = `${p.sku} ${p.name || ""} ${p.profile?.summary || ""} ${p.profile?.category || ""} ${p.profile?.subcategory || ""}`;
  return hay.toLowerCase().includes(q.toLowerCase());
}

export function ProductList({ filter, query, dialogs, focus, onFocus }: {
  filter: Filter; query: string; dialogs: Dialogs; focus: number | null; onFocus: (productId: number, frameId: number) => void;
}) {
  const { state } = useProject();
  const q = query.trim();
  const shown = state.products.filter((p) => matchesFilter(p, filter) && matchesQuery(p, q));
  return (
    <>
      {state.warnings.length > 0 && (
        <div className="warns">{state.warnings.map((w) => <div key={w}>{w}</div>)}</div>
      )}
      {!state.products.length ? (
        <div className="empty">Товаров пока нет. Нажмите «Загрузить фото» — сервис сам разложит снимки по товарам.</div>
      ) : !shown.length ? (
        <div className="empty">{q ? `Ничего не найдено по «${q}»` : "Под фильтр ничего не подходит"}</div>
      ) : (
        shown.map((p) => <ProductCard key={p.id} product={p} dialogs={dialogs} focus={focus} onFocus={onFocus} />)
      )}
    </>
  );
}
