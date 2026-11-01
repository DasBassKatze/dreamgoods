import { useCallback, useEffect, useRef, useState } from "react";
import { projectApi } from "../api/client";
import type { ProjectState } from "../api/types";

/** Опрос только видимой вкладки: 2 с в работе, 15 с в простое. */
export function useProjectState(projectId: number | null) {
  const [state, setState] = useState<ProjectState | null>(null);
  const [offline, setOffline] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const gen = useRef(0);
  const request = useRef(0);

  const load = useCallback(async () => {
    if (projectId == null) return;
    const my = gen.current;
    const sequence = ++request.current;
    try {
      const s = await projectApi(projectId).state();
      if (my !== gen.current || sequence !== request.current) return;
      setState(s);
      setOffline(false);
      return s;
    } catch {
      if (my === gen.current && sequence === request.current) setOffline(true);
    }
  }, [projectId]);

  useEffect(() => {
    gen.current += 1;
    setState(null);
    if (projectId == null) return;
    let alive = true;
    let running = false;
    const tick = async () => {
      if (!alive || running || document.hidden) return;
      window.clearTimeout(timer.current);
      running = true;
      const s = await load();
      running = false;
      if (!alive) return;
      timer.current = window.setTimeout(tick, s?.runner.busy ? 2000 : 15000);
    };
    const visible = () => {
      window.clearTimeout(timer.current);
      if (!document.hidden) void tick();
    };
    document.addEventListener("visibilitychange", visible);
    tick();
    return () => {
      alive = false;
      gen.current += 1;
      document.removeEventListener("visibilitychange", visible);
      window.clearTimeout(timer.current);
    };
  }, [projectId, load]);

  return { state, offline, reload: load };
}

