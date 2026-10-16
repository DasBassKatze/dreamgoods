import type { Route } from "../hooks/useRoute";
import { Icon } from "./Icon";

const ITEMS: [Route, string][] = [["import", "Загрузка фото"], ["presets", "Пресеты"], ["personas", "Модели"], ["styles", "Оформление"]];
export const SECTION_ROUTES: Route[] = ITEMS.map(([r]) => r);

/** Над разделами съёмки: путь назад к генерации и переключение между настройками проекта. */
export function SectionNav({ route, go }: { route: Route; go: (r: Route) => void }) {
  return (
    <nav className="section-nav" aria-label="Настройки съёмки">
      <button className="crumb" onClick={() => go("products")}><Icon name="chevron" size={14} /> Генерация</button>
      <span className="pills">
        {ITEMS.map(([r, label]) => (
          <button key={r} className={route === r ? "on" : ""} onClick={() => go(r)}>
            <Icon name={r} size={15} /> {label}
          </button>
        ))}
      </span>
    </nav>
  );
}

const ANALYTICS: [Route, string, string][] = [["m-analytics", "Аналитика проекта", "m-analytics"], ["m-reports", "Отчёты сервиса", "m-reports"]];
export const ANALYTICS_ROUTES: Route[] = ANALYTICS.map(([r]) => r);

/** «Аналитика и отчёты» мастера: два подраздела — живая аналитика открытого проекта и отчёты сервиса за период. */
export function AnalyticsNav({ route, go }: { route: Route; go: (r: Route) => void }) {
  return (
    <nav className="section-nav" aria-label="Аналитика и отчёты">
      <span className="pills">
        {ANALYTICS.map(([r, label, icon]) => (
          <button key={r} className={route === r ? "on" : ""} onClick={() => go(r)}><Icon name={icon} size={15} /> {label}</button>
        ))}
      </span>
    </nav>
  );
}
