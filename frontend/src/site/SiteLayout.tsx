import { useEffect, useState, type ReactNode } from "react";
import { authApi } from "../api/client";
import { useScrollState } from "./Interactive";

export const BOOT = "M62 18h46c4 0 7 3 7 7v78c0 8 5 14 13 17l30 11c12 4 20 14 20 26v8c0 4-3 7-7 7H48c-5 0-9-4-9-9v-18c0-10 3-19 9-27 6-9 8-19 8-30V25c0-4 3-7 6-7z";

export function Logo() {
  return (
    <a className="site-logo" href="/" aria-label="DreamGoods — на главную">
      <svg width="26" height="26" viewBox="0 0 20 20" aria-hidden="true">
        <defs><linearGradient id="site-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#7c3aed" /><stop offset="1" stopColor="#3b82f6" /></linearGradient></defs>
        <path fill="url(#site-grad)" d="M9 1.5c.75 4.4 2.3 5.95 6.7 6.7-4.4.75-5.95 2.3-6.7 6.7-.75-4.4-2.3-5.95-6.7-6.7 4.4-.75 5.95-2.3 6.7-6.7z" />
        <path fill="url(#site-grad)" d="M16 12.5c.3 1.6.9 2.2 2.5 2.5-1.6.3-2.2.9-2.5 2.5-.3-1.6-.9-2.2-2.5-2.5 1.6-.3 2.2-.9 2.5-2.5z" />
      </svg>
      <span>DreamGoods</span>
    </a>
  );
}

/** Вошёл ли посетитель — чтобы показать «Открыть студию» вместо «Войти». */
export function useSignedIn() {
  const [me, setMe] = useState<boolean | null>(null);
  useEffect(() => { authApi.me().then(() => setMe(true)).catch(() => setMe(false)); }, []);
  return me;
}

export function SiteLayout({ page, children }: { page: "home" | "pricing" | "legal"; children: ReactNode }) {
  const signedIn = useSignedIn();
  const [open, setOpen] = useState(false);
  const home = page === "home" ? "" : "/";
  const { scrolled, active } = useScrollState(page === "home" ? ["how", "features", "markets", "who", "prices", "faq"] : []);
  const on = (id: string) => (page === "home" && active === id ? "on" : "");
  return (
    <div className="site">
      <header className={`site-head ${scrolled ? "scrolled" : ""}`}>
        <div className="site-wrap site-head-in">
          <Logo />
          <nav className={`site-nav ${open ? "open" : ""}`} aria-label="Разделы сайта" onClick={() => setOpen(false)}>
            <a href={`${home}#how`} className={on("how")}>Как это работает</a>
            <a href={`${home}#features`} className={on("features") || on("markets") || on("who")}>Возможности</a>
            <a href="/pricing" className={page === "pricing" || on("prices") ? "on" : ""}>Цены и оплата</a>
            <a href={`${home}#faq`} className={on("faq")}>Вопросы</a>
          </nav>
          <span className="site-spacer" />
          {signedIn ? (
            <a className="site-btn primary" href="/studio">Открыть студию</a>
          ) : (
            <>
              <a className="site-btn ghost hide-sm" href="/studio">Войти</a>
              <a className="site-btn primary" href="/studio?register">Попробовать</a>
            </>
          )}
          <button className="site-burger" aria-label="Меню" aria-expanded={open} onClick={() => setOpen(!open)}>
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 6h14M3 10h14M3 14h14" /></svg>
          </button>
        </div>
      </header>
      <main>{children}</main>
      <footer className="site-foot">
        <div className="site-wrap site-foot-in">
          <div className="site-foot-brand">
            <Logo />
            <p>ИИ-фотостудия для карточек маркетплейсов.</p>
          </div>
          <nav aria-label="Ссылки">
            <a href="/studio">Студия</a>
            <a href="/pricing">Цены и оплата</a>
            <a href="/#features">Возможности</a>
            <a href="/#faq">Вопросы</a>
          </nav>
          <nav aria-label="Документы" className="site-foot-legal">
            <a href="/legal/terms">Пользовательское соглашение</a>
            <a href="/legal/privacy">Политика обработки персональных данных</a>
            <a href="/legal/pd_consent">Согласие на обработку данных</a>
          </nav>
          <small>© {new Date().getFullYear()} DreamGoods. Все права защищены.</small>
        </div>
      </footer>
    </div>
  );
}
