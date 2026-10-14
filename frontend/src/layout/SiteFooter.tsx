import { useEffect, useState } from "react";

let cached: string | null = null;

/** Подпись сайта: правообладатель и версия (версию отдаёт сервер — /api/health). */
export function SiteFooter({ className = "" }: { className?: string }) {
  const [version, setVersion] = useState(cached);
  useEffect(() => {
    if (cached) return;
    fetch("/api/health").then((r) => r.json()).then((d) => { cached = d.version; setVersion(d.version); }).catch(() => {});
  }, []);
  return (
    <footer className={`site-footer ${className}`}>
      <span>© {new Date().getFullYear()} DreamGoods. Все права защищены.</span>
      {version && <span className="ft-ver" title="Версия сервиса">Версия {version}</span>}
    </footer>
  );
}
