import { useEffect, useState, type ReactNode } from "react";
import { isDesktop } from "./runtime";

export function DesktopShell({ children }: { children: ReactNode }) {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!isDesktop) return;
    document.documentElement.classList.add("desktop");
    const sync = () => void window.dgDesktop!.state().then(s => setMaximized(s.maximized)).catch(() => {});
    window.addEventListener("resize", sync); sync();
    return () => window.removeEventListener("resize", sync);
  }, []);
  if (!isDesktop) return children;
  const maximize = () => void window.dgDesktop!.maximize().then(() => window.dgDesktop!.state()).then(s => setMaximized(s.maximized));
  return <div className={`desktop-shell ${maximized ? "maximized" : ""}`}>
    <div className="desktop-titlebar" onDoubleClick={maximize}>
      <span className="desktop-emblem">✦</span><b>DG Desktop</b><span className="desktop-title-hint">DreamGoods</span>
      <span className="spacer" />
      <div className="desktop-window-controls" onDoubleClick={e => e.stopPropagation()}>
        <button aria-label="Свернуть окно" title="Свернуть" onClick={() => void window.dgDesktop!.minimize()}>─</button>
        <button aria-label="Развернуть окно" title={maximized ? "Восстановить" : "Развернуть"} onClick={maximize}>{maximized ? "❐" : "□"}</button>
        <button className="desktop-window-close" aria-label="Закрыть приложение" title="Закрыть" onClick={() => void window.dgDesktop!.close()}>✕</button>
      </div>
    </div>
    <div className="desktop-content">{children}</div>
  </div>;
}
