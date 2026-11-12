import { useEffect, useState, type ReactNode } from "react";
import { isDesktop } from "./runtime";

export function DesktopShell({ children }: { children: ReactNode }) {
  const [maximized, setMaximized] = useState(false);
  const [focused, setFocused] = useState(true);
  useEffect(() => {
    if (!isDesktop) return;
    document.documentElement.classList.add("desktop");
    const sync = () => void window.dgDesktop!.state().then(s => setMaximized(s.maximized)).catch(() => {});
    const focus = () => setFocused(true), blur = () => setFocused(false);
    window.addEventListener("resize", sync);
    window.addEventListener("focus", focus); window.addEventListener("blur", blur); sync();
    return () => {
      window.removeEventListener("resize", sync);
      window.removeEventListener("focus", focus); window.removeEventListener("blur", blur);
    };
  }, []);
  if (!isDesktop) return children;
  const maximize = () => void window.dgDesktop!.maximize().then(() => window.dgDesktop!.state()).then(s => setMaximized(s.maximized));
  return <div className={`desktop-shell ${maximized ? "maximized" : ""} ${focused ? "" : "inactive"}`}>
    <div className="desktop-titlebar" onDoubleClick={maximize}>
      <span className="desktop-emblem">✦</span><b>DG Desktop</b><span className="desktop-title-hint">DreamGoods</span>
      <span className="spacer" />
      <div className="desktop-window-controls" onDoubleClick={e => e.stopPropagation()}>
        <button aria-label="Свернуть окно" title="Свернуть" onClick={() => void window.dgDesktop!.minimize()}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5h10" /></svg></button>
        <button aria-label="Развернуть окно" title={maximized ? "Восстановить" : "Развернуть"} onClick={maximize}><svg viewBox="0 0 16 16" aria-hidden="true">{maximized ? <path d="M5.5 5.5v-3h8v8h-3m-8-5h8v8h-8z" /> : <rect x="3.5" y="3.5" width="9" height="9" rx="1" />}</svg></button>
        <button className="desktop-window-close" aria-label="Закрыть приложение" title="Закрыть" onClick={() => void window.dgDesktop!.close()}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg></button>
      </div>
    </div>
    <div className="desktop-content">{children}</div>
  </div>;
}
