export interface DesktopBridge {
  minimize: () => Promise<void>;
  maximize: () => Promise<void>;
  close: () => Promise<void>;
  dataInfo: () => Promise<void>;
  interfaceMode?: (userId: number, mode?: "simple" | "advanced") => Promise<"simple" | "advanced" | undefined>;
  mode: (mode: "login" | "workspace") => Promise<void>;
  state: () => Promise<{ maximized: boolean }>;
}
declare global { interface Window { dgDesktop?: DesktopBridge; } }
export const isDesktop = !!window.dgDesktop;
