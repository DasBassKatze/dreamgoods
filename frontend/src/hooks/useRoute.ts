import { useCallback, useEffect, useState } from "react";

export type Route =
  | "products" | "review" | "gallery" | "history" | "import" | "presets" | "personas" | "styles" | "balance" | "account"
  | "m-analytics" | "m-users" | "m-keys" | "m-finance" | "m-reports" | "m-log" | "m-settings" | "m-legal";

const ALL: Route[] = ["products", "review", "gallery", "history", "import", "presets", "personas", "styles", "balance", "account",
  "m-analytics", "m-users", "m-keys", "m-finance", "m-reports", "m-log", "m-settings", "m-legal"];

const read = (): Route => {
  const h = window.location.hash.replace(/^#\/?/, "") as Route;
  return ALL.includes(h) ? h : "products";
};

/** Разделы сайта в адресе (#/presets) — работают «назад» в браузере и ссылки на раздел. */
export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const h = () => setRoute(read());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  const go = useCallback((r: Route) => {
    if (r !== read()) window.location.hash = `/${r}`;
    setRoute(r);
  }, []);
  return [route, go];
}

