import type { Me, ProjectRef } from "../api/types";
import type { Route } from "../hooks/useRoute";
import { rub } from "../lib/format";
import { Icon } from "./Icon";
import { SiteFooter } from "./SiteFooter";

interface Props {
  me: Me;
  route: Route;
  go: (r: Route) => void;
  projects: ProjectRef[];
  projectId: number | null;
  onProject: (id: number) => void;
  onNewProject: () => void;
  balance: { balance: number; billing: boolean; client?: string } | null;
  /** мастеру: баланс Polza (по ключу текущего проекта) */
  polza?: { value: number | null; error: string } | null;
  reviewCount: number;
  busy: boolean;
  onLogout: () => void;
  open: boolean;
  onToggle: () => void;
}

const WORK: [Route, string][] = [
  ["products", "Товары и кадры"],
  ["import", "Загрузка фото"],
  ["presets", "Пресеты съёмки"],
  ["personas", "Модели"],
  ["styles", "Оформление"],
];
const MASTER: [Route, string][] = [
  ["m-users", "Пользователи"],
  ["m-finance", "Финансы"],
  ["m-keys", "Ключи Polza"],
  ["m-analytics", "Аналитика"],
  ["m-log", "Журнал сервера"],
  ["m-settings", "Тех. настройки"],
];

/** Боковое меню: проект, разделы работы, кабинет; для мастер-аккаунта — управление сервисом. */
export function Sidebar(p: Props) {
  const master = p.me.role === "master";
  const groups = new Map<string, ProjectRef[]>();
  for (const pr of p.projects) groups.set(pr.client, [...(groups.get(pr.client) || []), pr]);
  const low = p.balance?.billing && p.balance.balance <= 0;

  const item = ([r, label]: [Route, string], extra?: React.ReactNode) => (
    <button key={r} className={`nav ${p.route === r ? "on" : ""}`} aria-current={p.route === r ? "page" : undefined}
      onClick={() => { p.go(r); if (p.open) p.onToggle(); }}>
      <Icon name={r} /><span>{label}</span>{extra}
    </button>
  );

  return (
    <>
      <button className="burger" onClick={p.onToggle} aria-label="Меню"><Icon name="menu" /></button>
      {p.open && <div className="scrim" onClick={p.onToggle} />}
      <nav className={`sidebar ${p.open ? "open" : ""}`}>
        <div className="logo">Dream<b>Goods</b></div>

        <div className="proj">
          <label htmlFor="proj-select">Проект</label>
          <div className="proj-row">
            <select id="proj-select" value={p.projectId ?? ""} onChange={(e) => p.onProject(+e.target.value)}>
              {master
                ? [...groups.entries()].map(([client, list]) => (
                    <optgroup key={client} label={client}>
                      {list.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                    </optgroup>
                  ))
                : p.projects.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <button className="icon" title="Новый проект" aria-label="Новый проект" onClick={p.onNewProject}><Icon name="plus" size={16} /></button>
          </div>
        </div>

        <div className="nav-group">
          {WORK.map((w) => item(w, w[0] === "products" ? (
            <>{p.busy && <em className="dot run" title="Идёт генерация" />}
              {p.reviewCount > 0 && <em className="badge-n" title="Кадры ждут вашего решения">{p.reviewCount}</em>}</>
          ) : undefined))}
        </div>

        {master && (
          <div className="nav-group">
            <div className="nav-title">Управление сервисом</div>
            {MASTER.map((m) => item(m))}
          </div>
        )}

        <span className="spacer-v" />

        {master && p.polza && (
          <button className={`wallet polza ${p.route === "m-keys" ? "on" : ""} ${p.polza.error ? "low" : ""}`}
            onClick={() => p.go("m-keys")} title="Баланс ключа Polza, на котором работает текущий проект. Все ключи — в «Ключи Polza»">
            <span>Баланс Polza</span>
            <b>{p.polza.value == null ? (p.polza.error ? "ошибка ключа" : "…") : rub(p.polza.value)}</b>
            {p.balance?.billing
              ? <small className="sub">кабинет «{p.balance.client}»: {rub(p.balance.balance)}</small>
              : <small className="sub">ваши проекты — напрямую с этого баланса</small>}
          </button>
        )}
        {!master && p.balance?.billing && (
          <button className={`wallet ${low ? "low" : ""} ${p.route === "balance" ? "on" : ""}`} onClick={() => p.go("balance")}>
            <span>Баланс</span>
            <b>{rub(p.balance.balance)}</b>
            {low && <small>пополните, чтобы запускать генерацию</small>}
          </button>
        )}
        {!p.balance?.billing && !master && item(["balance", "Расходы"])}

        <div className="me">
          <button className={`me-btn ${p.route === "account" ? "on" : ""}`} onClick={() => p.go("account")} title="Учётная запись">
            <span className="avatar">{(p.me.name || p.me.email).slice(0, 1).toUpperCase()}</span>
            <span className="me-text"><b>{p.me.name}</b><small>{master ? "мастер-аккаунт" : p.me.email}</small></span>
          </button>
          <button className="icon" title="Выйти" aria-label="Выйти" onClick={p.onLogout}><Icon name="logout" size={16} /></button>
        </div>
        <SiteFooter />
      </nav>
    </>
  );
}
