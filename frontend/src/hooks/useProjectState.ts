import { useCallback, useEffect, useRef, useState } from "react";
import { projectApi } from "../api/client";
import type { ProjectState } from "../api/types";

/** Состояние проекта с опросом сервера: каждые 2 с, пока идёт работа, иначе каждые 5 с. */
export function useProjectState(projectId: number | null) {
  const [state, setState] = useState<ProjectState | null>(null);
  const [offline, setOffline] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const gen = useRef(0);

  const load = useCallback(async () => {
    if (projectId == null) return;
    const my = gen.current;
    try {
      const s = await projectApi(projectId).state();
      if (my !== gen.current) return; // проект сменился, пока шёл запрос
      setState(s);
      setOffline(false);
      return s;
    } catch {
      if (my === gen.current) setOffline(true);
    }
  }, [projectId]);

  useEffect(() => {
    gen.current += 1;
    setState(null);
    if (projectId == null) return;
    let alive = true;
    const tick = async () => {
      const s = await load();
      if (!alive) return;
      timer.current = window.setTimeout(tick, s?.runner.busy ? 2000 : 5000);
    };
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer.current);
    };
  }, [projectId, load]);

  return { state, offline, reload: load };
}
