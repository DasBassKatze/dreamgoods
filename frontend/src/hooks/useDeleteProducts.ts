import { useProject } from "../ProjectContext";
import { useUI } from "../components/ui";

export function useDeleteProducts() {
  const { api, state, reload, run, selected, setSelected, pickedFrames, setPicked } = useProject();
  const ui = useUI();
  return (ids: number[]) => run(async () => {
    if (!ids.length) return;
    if (!(await ui.confirm({ title: ids.length === 1 ? "Удалить товар?" : `Удалить товары (${ids.length})?`,
      text: "Товары и связанные кадры будут удалены. История расходов сохранится. Это действие нельзя отменить.", ok: "Удалить", danger: true }))) return;
    await api.deleteProducts(ids);
    const removed = new Set(ids);
    const frames = new Set(state.products.filter(p => removed.has(p.id)).flatMap(p => p.frames.map(f => f.id)));
    setSelected([...selected].filter(id => !removed.has(id)));
    setPicked([...pickedFrames].filter(id => !frames.has(id)));
    await reload();
    ui.toast(`Удалено товаров: ${ids.length}`);
  });
}
