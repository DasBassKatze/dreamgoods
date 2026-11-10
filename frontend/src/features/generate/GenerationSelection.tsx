import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useProject } from "../../ProjectContext";

type Target = "selected" | "visible" | "project";
const SelectionContext = createContext<{ target: Target; setTarget: (value: Target) => void; ids: number[]; visibleIds: number[]; selectedIds: number[]; hidden: number; label: string } | null>(null);

export function GenerationSelection({ visibleIds, children }: { visibleIds: number[]; children: ReactNode }) {
  const { selected, state } = useProject();
  const all = state.products.map(p => p.id);
  const selectedIds = all.filter(id => selected.has(id));
  const [target, setTarget] = useState<Target>(() => selectedIds.length ? "selected" : "visible");
  const previous = useRef(selectedIds.length);
  useEffect(() => {
    if (!previous.current && selectedIds.length) setTarget("selected");
    previous.current = selectedIds.length;
  }, [selectedIds.length]);
  const ids = target === "selected" ? selectedIds : target === "visible" ? visibleIds : all;
  const hidden = selectedIds.filter(id => !visibleIds.includes(id)).length;
  const label = target === "selected" ? `Выбранные товары: ${ids.length}` : target === "visible" ? `Товары в списке: ${ids.length}` : `Весь проект: ${ids.length}`;
  return <SelectionContext.Provider value={{ target, setTarget, ids, visibleIds, selectedIds, hidden, label }}>{children}</SelectionContext.Provider>;
}
export function useGenerationSelection() {
  const value = useContext(SelectionContext);
  if (!value) throw new Error("GenerationSelection missing");
  return value;
}
