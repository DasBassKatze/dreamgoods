import { useCallback, useEffect, useRef, useState } from "react";
import { projectApi } from "../api/client";
import type { ProjectState } from "../api/types";

/** SSE invalidates the visible page; periodic refresh covers non-job edits and unsupported proxies. */
export function useProjectState(projectId: number | null, page = 1, query = "", status = "all") {
  const [state, setState] = useState<ProjectState | null>(null);
  const [offline, setOffline] = useState(false);
  const generation = useRef(0);
  const serial = useRef(0);
  const load = useCallback(async () => {
    if (projectId == null) return;
    const mine = generation.current, request = ++serial.current;
    try {
      const data = await projectApi(projectId).state({ page, query, status });
      if (mine !== generation.current || request !== serial.current) return;
      setState(data); setOffline(false);
      return data;
    } catch {
      if (mine === generation.current && request === serial.current) setOffline(true);
    }
  }, [projectId, page, query, status]);
  useEffect(() => {
    generation.current++;
    setState(null);
    if (projectId == null) return;
    let alive = true, timer: number | undefined, stream: EventSource | undefined;
    const tick = async () => {
      if (document.visibilityState !== "hidden") await load();
      if (alive) timer = window.setTimeout(tick, 30000);
    };
    const connect = () => {
      stream?.close();
      if (document.visibilityState === "hidden") return;
      let previous: string | undefined;
      stream = new EventSource(`/api/projects/${projectId}/events`);
      stream.onmessage = (e) => {
        const next = JSON.parse(e.data).version as string;
        if (previous !== undefined && previous !== next) void load();
        previous = next;
      };
    };
    const visible = () => { connect(); if (document.visibilityState !== "hidden") void load(); };
    void tick(); connect();
    document.addEventListener("visibilitychange", visible);
    return () => {
      alive = false; generation.current++; stream?.close(); window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [projectId, load]);
  return { state, offline, reload: load };
}
