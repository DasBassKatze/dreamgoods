import { useEffect, useRef, useState } from "react";
import type { Me } from "../api/types";
import type { Route } from "../hooks/useRoute";
import { rub } from "../lib/format";
import { Icon } from "./Icon";

const TABS: [Route, string][] = [
  ["products", "Генерация"],
  ["gallery", "Галерея"],
  ["history", "История"],
  ["balance", "Тарифы"],
];
/** Разделы, которые открываются кнопками со страницы генерации, — подсвечивают вкладку «Генерация». */
const UNDER_GEN: Route[] = ["products", "import", "presets", "personas", "styles"];
const MASTER: [Route, string][] = [
  ["m-users", "Пользователи"],
  ["m-finance", "Финансы"],
  ["m-keys", "Ключи Polza"],
  ["m-analytics", "Аналитика и отчёты"],
  ["m-log", "Журнал сервера"],
  ["m-settings", "Тех. настройки"],
];

interface Props {
  me: Me;
  route: Route;
  go: (r: Route) => void;
  balance: { balance: number; billing: boolean; client?: string } | null;
  polza?: { value: number | null; error: string } | null;
  reviewCount: number;
  busy: boolean;
  onLogout: () => void;
  onMenu: () => void;
}

/** Верхняя строка: логотип, разделы вкладками, баланс и учётная запись. */
export function TopBar(p: Props) {
  const master = p.me.role === "master";
  const [open, setOpen] = useState<"" | "manage" | "me">("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(""); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const pick = (r: Route) => { p.go(r); setOpen(""); };
  const initials = (p.me.name || p.me.email).split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  const low = !master && p.balance?.billing && p.balance.balance <= 0;

  return (
    <header className="topbar" ref={ref}>
      <button className="tb-burger" onClick={p.onMenu} aria-label="Проекты"><Icon name="menu" /></button>
      <a className="brand" href="#/products" title="На главную — генерация" onClick={(e) => { e.preventDefault(); pick("products"); }}>
        <svg className="brand-mark" width="26" height="26" viewBox="0 0 20 20" aria-hidden="true">
          <defs><linearGradient id="dg-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#7c3aed" /><stop offset="1" stopColor="#3b82f6" /></linearGradient></defs>
          <path fill="url(#dg-grad)" d="M9 1.5c.75 4.4 2.3 5.95 6.7 6.7-4.4.75-5.95 2.3-6.7 6.7-.75-4.4-2.3-5.95-6.7-6.7 4.4-.75 5.95-2.3 6.7-6.7z" />
          <path fill="url(#dg-grad)" d="M16 12.5c.3 1.6.9 2.2 2.5 2.5-1.6.3-2.2.9-2.5 2.5-.3-1.6-.9-2.2-2.5-2.5 1.6-.3 2.2-.9 2.5-2.5z" />
        </svg>
        <span>DreamGoods</span>
      </a>
      <nav className="tabs-top" aria-label="Разделы">
        {TABS.map(([tab, label]) => {
          // у мастера своего баланса нет — «Тарифы» ведут в финансы кабинетов
          const r: Route = tab === "balance" && master ? "m-finance" : tab;
          const on = r === "products" ? UNDER_GEN.includes(p.route) : p.route === r;
          return (
          <button key={tab} className={on ? "on" : ""} aria-current={on ? "page" : undefined} onClick={() => pick(r)}>
            {label}
            {r === "products" && p.busy && <i className="dot-run" title="Идёт генерация" />}
            {r === "products" && p.reviewCount > 0 && <em className="tab-badge" title="Кадры ждут вашего решения">{p.reviewCount}</em>}
          </button>
          );
        })}
        {master && (
          <div className="menu-wrap">
            <button className={p.route.startsWith("m-") ? "on" : ""} onClick={() => setOpen(open === "manage" ? "" : "manage")}>
              <span className="lbl-long">Управление</span><span className="lbl-short">Ещё</span> <Icon name="chevron" size={14} />
            </button>
            {open === "manage" && (
              <div className="menu">
                {MASTER.map(([r, label]) => (
                  <button key={r} className={p.route === r || (r === "m-analytics" && p.route === "m-reports") ? "on" : ""} onClick={() => pick(r)}><Icon name={r} size={16} />{label}</button>
                ))}
              </div>
            )}
          </div>
        )}
      </nav>
      <span className="spacer" />
      {master && p.polza ? (
        <button className={`pill-balance ${p.polza.error ? "warn" : ""}`} onClick={() => pick("m-keys")}
          title={p.balance?.billing ? `Баланс Polza. Внутренний баланс кабинета «${p.balance.client}»: ${rub(p.balance.balance)}` : "Баланс Polza по ключу открытого проекта"}>
          <span className="coin"><Icon name="coin" size={16} /></span>
          {p.polza.value == null ? (p.polza.error ? "ошибка ключа" : "…") : rub(p.polza.value)}
          <small>Polza</small>
        </button>
      ) : p.balance?.billing ? (
        <button className={`pill-balance ${low ? "warn" : ""}`} onClick={() => pick("balance")} title="Баланс и история списаний">
          <span className="coin"><Icon name="coin" size={16} /></span>{rub(p.balance.balance)}
        </button>
      ) : null}
      <div className="menu-wrap">
        <button className="avatar-btn" onClick={() => setOpen(open === "me" ? "" : "me")} aria-label="Учётная запись">{initials}</button>
        {open === "me" && (
          <div className="menu right">
            <div className="menu-head"><b>{p.me.name}</b><small>{master ? "мастер-аккаунт" : p.me.email}</small></div>
            <button onClick={() => pick("account")}>Учётная запись</button>
            {!master && <button onClick={() => pick("balance")}>{p.balance?.billing ? "Баланс и история" : "Расходы"}</button>}
            <button className="danger" onClick={p.onLogout}><Icon name="logout" size={16} />Выйти</button>
          </div>
        )}
      </div>
    </header>
  );
}
