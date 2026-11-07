import { useEffect, useState } from "react";
import { projectApi } from "../api/client";

export type KeyStatus = { value: number | null; error: string; checking: boolean; checked_at: number; configured: boolean };
export const KEY_STATUS_CHANGED = "dg:key-status-changed";

export function useKeyStatus(projectId: number | null, enabled: boolean) {
  const [result, setResult] = useState<{ project: number; status: KeyStatus } | null>(null);
  useEffect(() => {
    if (!enabled || projectId == null) return;
    let alive = true, running = false;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      clearTimeout(timer);
      if (!alive || running || document.hidden) return;
      running = true;
      let delay = 30000;
      try {
        const status = await projectApi(projectId).keyStatus();
        if (!alive) return;
        setResult({ project: projectId, status });
        if (status.checking) delay = 2000;
      } catch {
        if (alive) setResult({ project: projectId, status: { value: null, error: "Нет связи с сервером", checking: false, checked_at: 0, configured: true } });
        delay = 5000;
      } finally {
        running = false;
        if (alive && !document.hidden) timer = setTimeout(refresh, delay);
      }
    };
    const wake = () => { if (!document.hidden) void refresh(); else clearTimeout(timer); };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    window.addEventListener(KEY_STATUS_CHANGED, wake);
    void refresh();
    return () => { alive = false; clearTimeout(timer); document.removeEventListener("visibilitychange", wake); window.removeEventListener("focus", wake); window.removeEventListener(KEY_STATUS_CHANGED, wake); };
  }, [projectId, enabled]);
  return result?.project === projectId ? result.status : null;
}
