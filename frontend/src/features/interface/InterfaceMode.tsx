import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { usePersistentState } from "../../hooks/usePersistentState";

const ModeContext = createContext({ advanced: false, setAdvanced: (_value: boolean) => {} });

export function InterfaceModeProvider({ userId, children }: { userId: number; children: ReactNode }) {
  const [mode, setMode] = usePersistentState(`interface-mode:${userId}`, "simple");
  return <ModeContext.Provider value={{ advanced: mode === "advanced", setAdvanced: value => setMode(value ? "advanced" : "simple") }}><div className="studio-shell">{children}</div></ModeContext.Provider>;
}
export const useInterfaceMode = () => useContext(ModeContext);

export function ModeSwitch() {
  const { advanced, setAdvanced } = useInterfaceMode();
  return <div className="workspace-mode">
    <span>Рабочее пространство</span><span className="spacer" />
    <div className="mode-switch" role="group" aria-label="Режим интерфейса">
      <button aria-pressed={!advanced} onClick={() => setAdvanced(false)}>Простой</button>
      <button aria-pressed={advanced} onClick={() => setAdvanced(true)}>Расширенный</button>
    </div>
    <small>{advanced ? "Все параметры под рукой" : "Основные действия"}</small>
  </div>;
}

export function AdvancedFields({ title, summary, children }: { title: string; summary?: ReactNode; children: ReactNode }) {
  const { advanced } = useInterfaceMode();
  const [open, setOpen] = useState(advanced);
  useEffect(() => setOpen(advanced), [advanced]);
  return <details className="advanced-fields" open={open} onToggle={e => setOpen(e.currentTarget.open)}>
    <summary><b>{title}</b>{summary && <span>{summary}</span>}</summary><div className="advanced-body">{children}</div>
  </details>;
}
