import { useCallback, useEffect, useMemo, useState } from "react";
import { adminApi } from "../../api/client";
import type { ReportSelection, ServiceReport } from "../../api/types";
import { useUI } from "../../components/ui";
import { usePersistentState } from "../../hooks/usePersistentState";
import { Icon } from "../../layout/Icon";
import { rub } from "../../lib/format";

type Mode = "general" | "custom";
type Preset = "month" | "prev-month" | "3m" | "6m" | "12m" | "custom";
const PRESETS: [Preset, string][] = [
  ["month", "Этот месяц"], ["prev-month", "Прошлый месяц"], ["3m", "3 месяца"], ["6m", "Полгода"], ["12m", "Год"],
  ["custom", "Свои даты"],
];
const RATES: [number, string][] = [[0.06, "6% — УСН «Доходы» / НПД с ИП и компаний"], [0.04, "4% — НПД с физлиц"],
  [0.08, "8% — АУСН «Доходы»"], [0, "не считать"]];

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Фиксированные периоды: «3 месяца» — текущий и два прошлых календарных месяца, по сегодняшний день. */
function range(p: Preset): [string, string] {
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth();
  switch (p) {
    case "prev-month": return [iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))];
    case "3m": return [iso(new Date(y, m - 2, 1)), iso(now)];
    case "6m": return [iso(new Date(y, m - 5, 1)), iso(now)];
    case "12m": return [iso(new Date(y, m - 11, 1)), iso(now)];
    default: return [iso(new Date(y, m, 1)), iso(now)];
  }
}

const fmtDay = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
const fmtDate = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
const num = (v: number) => v.toLocaleString("ru-RU");

const SHORT: Record<string, string> = {
  topups: "Поступило от клиентов (пополнения)", adjust: "Корректировки балансов", charged: "Списано с балансов за услуги",
  charged_cost: "Себестоимость списаний", margin: "Наценка по списаниям", polza: "Весь расход Polza",
  polza_unbilled: "Расход Polza без оплаты клиентом", result: "Итог: списано − расход Polza", balances_end: "Остаток на балансах на конец",
  images: "Изображений", edits: "Правок", checks: "ИИ-проверок", errors: "Ошибок заданий", clients_paying: "Платящих пользователей",
  usn_tax: "Налог с пополнений (оценка)",
};
const STRONG = new Set(["topups", "margin"]);

/** Мастер: отчёт за период. «Общий» — готовый набор показателей; «Настраиваемый» — свои показатели, разделы и колонки. */
export function ReportsPage() {
  const ui = useUI();
  const [mode, setMode] = usePersistentState<Mode>("report_mode", "general");
  const [preset, setPreset] = useState<Preset>("month");
  const [[from, to], setRange] = useState<[string, string]>(range("month"));
  const [client, setClient] = useState<number | null>(null);
  const [rate, setRate] = useState(0.06);
  const [custom, setCustom] = usePersistentState<ReportSelection | null>("report_custom", null);
  const [rep, setRep] = useState<ServiceReport | null>(null);
  const [loading, setLoading] = useState(false);
  const q = useMemo(() => ({ from, to, client, rate }), [from, to, client, rate]);

  const load = useCallback(async () => {
    if (!from || !to) return;
    setLoading(true);
    try {
      setRep(await adminApi.report(q));
    } catch (e) {
      ui.toast((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [q, from, to, ui]);
  useEffect(() => { load(); }, [load]);

  const pick = (p: Preset) => {
    setPreset(p);
    if (p !== "custom") setRange(range(p));
  };

  const cat = rep?.catalog;
  const all: ReportSelection | null = cat ? { metrics: cat.metrics.map((x) => x.key), sections: cat.sections.map((x) => x.key),
    cols: cat.cols.map((x) => x.key) } : null;
  const sel: ReportSelection | null = !cat ? null : mode === "general" ? cat.general : (custom || cat.general);
  const toggle = (group: keyof ReportSelection, key: string, on: boolean) => {
    if (!sel || !cat) return;
    const order = (group === "metrics" ? cat.metrics : group === "sections" ? cat.sections : cat.cols).map((x) => x.key);
    const next = new Set(sel[group]);
    if (on) next.add(key); else next.delete(key);
    setCustom({ ...sel, [group]: order.filter((k) => next.has(k)) });
  };
  const has = (group: keyof ReportSelection, key: string) => !!sel?.[group].includes(key);

  const s = rep?.summary;
  const maxDay = Math.max(1, ...(rep?.by_day || []).map((d) => Math.max(d.charge, d.cost, d.topup)));
  const hint = (k: string): string => {
    if (!s) return "";
    switch (k) {
      case "topups": return "Доход для налога на УСН и НПД — в день поступления денег";
      case "charged": return `${num(s.clients_paying)} платящих пользователей`;
      case "margin": return s.markup ? `×${s.markup.toLocaleString("ru-RU")} к себестоимости` : "";
      case "polza": return s.polza_unbilled > 0 ? `${rub(s.polza_unbilled)} — без оплаты клиентом` : "";
      case "balances_end": return "Деньги клиентов, ещё не потраченные";
      case "images": return `из них правок ${num(s.edits)} · проверок ${num(s.checks)}`;
      case "usn_tax": return `${s.usn_rate * 100}% без вычета страховых взносов`;
      default: return "";
    }
  };
  const value = (k: string, type: "rub" | "num") => {
    const v = (s as unknown as Record<string, number>)[k] ?? 0;
    return type === "rub" ? rub(v) : num(v);
  };
  const tiles = cat && s ? cat.metrics.filter((m) => has("metrics", m.key) && !(m.key === "usn_tax" && s.usn_rate === 0)) : [];
  const cols = cat ? cat.cols.filter((c) => has("cols", c.key)) : [];

  return (
    <section className="page reports">
      <div className="page-head">
        <h1>Отчёты</h1>
        {rep && <span className="hint">{fmtDate(rep.from)} — {fmtDate(rep.to)}{rep.client_name ? ` · ${rep.client_name}` : ""}</span>}
        <span className="spacer" />
        <button onClick={load} disabled={loading}>{loading ? "Считаю…" : "Обновить"}</button>
        <a className="btn primary" href={adminApi.reportCsvUrl(q, sel || undefined)}><Icon name="download" size={16} /> Скачать CSV</a>
      </div>

      <div className="rep-filters">
        <div className="rep-row">
          <span className="seg">
            <button className={mode === "general" ? "on" : ""} onClick={() => setMode("general")}>Общий отчёт</button>
            <button className={mode === "custom" ? "on" : ""} onClick={() => setMode("custom")}>Настраиваемый</button>
          </span>
          <span className="hint">{mode === "general" ? "Основные показатели и все разделы." : "Отметьте, что показать на экране и выгрузить в CSV — выбор запоминается."}</span>
        </div>
        <div className="pills">
          {PRESETS.map(([k, label]) => <button key={k} className={preset === k ? "on" : ""} onClick={() => pick(k)}>{label}</button>)}
        </div>
        <div className="rep-row">
          <label className="ps-field"><span>С</span>
            <input type="date" value={from} max={to} onChange={(e) => { setPreset("custom"); setRange([e.target.value, to]); }} /></label>
          <label className="ps-field"><span>По</span>
            <input type="date" value={to} min={from} onChange={(e) => { setPreset("custom"); setRange([from, e.target.value]); }} /></label>
          <label className="ps-field"><span>Пользователь</span>
            <select value={client ?? ""} onChange={(e) => setClient(e.target.value ? +e.target.value : null)}>
              <option value="">Все пользователи</option>
              {(rep?.client_list || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          <label className="ps-field"><span>Оценка налога с пополнений</span>
            <select value={rate} onChange={(e) => setRate(+e.target.value)}>
              {RATES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select></label>
        </div>

        {mode === "custom" && cat && sel && all && (
          <div className="rep-custom">
            <Group title="Показатели сводки" items={cat.metrics.map((m) => [m.key, SHORT[m.key] || m.label])}
              isOn={(k) => has("metrics", k)} onToggle={(k, on) => toggle("metrics", k, on)}
              onAll={(on) => setCustom({ ...sel, metrics: on ? all.metrics : [] })} />
            <Group title="Разделы" items={cat.sections.map((x) => [x.key, x.label])}
              isOn={(k) => has("sections", k)} onToggle={(k, on) => toggle("sections", k, on)}
              onAll={(on) => setCustom({ ...sel, sections: on ? all.sections : [] })} />
            <Group title="Колонки таблицы «По пользователям»" items={cat.cols.map((x) => [x.key, x.label])}
              isOn={(k) => has("cols", k)} onToggle={(k, on) => toggle("cols", k, on)}
              onAll={(on) => setCustom({ ...sel, cols: on ? all.cols : [] })} disabled={!has("sections", "clients")} />
            <div className="row"><button className="link" onClick={() => setCustom(cat.general)}>вернуть набор общего отчёта</button></div>
          </div>
        )}
      </div>

      {!s || !rep || !sel ? <div className="empty">{loading ? "Считаю отчёт…" : "Нет данных"}</div> : (
        <>
          {tiles.length > 0 && (
            <div className="kpis">
              {tiles.map((m) => (
                <Kpi key={m.key} label={SHORT[m.key] || m.label} value={value(m.key, m.type)} hint={hint(m.key)} strong={STRONG.has(m.key)}
                  warn={(m.key === "result" && s.result < 0) || (m.key === "errors" && s.errors > 0)} />
              ))}
            </div>
          )}
          {has("metrics", "polza") && s.polza_unbilled > 0 && (
            <p className="hint">Расход Polza без оплаты клиентом — генерации мастера и кабинетов без внутреннего баланса.
              Он уменьшает итог, но не попадает в списания.</p>
          )}

          {has("sections", "by_day") && rep.by_day.length > 0 && (
            <div className="panel rep-chart">
              <div className="rep-chart-h"><b>По дням</b>
                <span className="legend"><i className="lg-charge" /> списано <i className="lg-cost" /> расход Polza <i className="lg-topup" /> пополнения</span>
              </div>
              <div className="rep-bars" role="img" aria-label="Списания, расход Polza и пополнения по дням">
                {rep.by_day.map((d) => (
                  <div key={d.day} className="rep-bar" title={`${fmtDay(d.day)}: списано ${rub(d.charge)}, Polza ${rub(d.cost)}, пополнения ${rub(d.topup)}, изображений ${d.images}`}>
                    <div className="rep-stack">
                      <i className="b-charge" style={{ height: `${(d.charge / maxDay) * 100}%` }} />
                      <i className="b-cost" style={{ height: `${(d.cost / maxDay) * 100}%` }} />
                      <i className="b-topup" style={{ height: `${(d.topup / maxDay) * 100}%` }} />
                    </div>
                    <small>{fmtDay(d.day)}</small>
                  </div>
                ))}
              </div>
            </div>
          )}

          {has("sections", "clients") && (
            <>
              <h2>По пользователям</h2>
              <div className="table-wrap">
                <table className="tbl">
                  <thead><tr><th>Пользователь</th>{cols.map((c) => <th key={c.key} className="num">{c.label}</th>)}</tr></thead>
                  <tbody>
                    {rep.clients.map((r) => (
                      <tr key={r.client_id ?? "none"}>
                        <td>{r.client}{!r.billing && r.client_id != null && <span className="hint"> · без баланса</span>}</td>
                        {cols.map((c) => {
                          const v = (r as unknown as Record<string, number | null>)[c.key];
                          return <td key={c.key} className={`num ${c.key === "margin" ? "strong" : ""}`}>
                            {v == null ? "—" : c.type === "rub" ? rub(v) : num(v)}</td>;
                        })}
                      </tr>
                    ))}
                    {!rep.clients.length && <tr><td colSpan={cols.length + 1} className="hint">За период операций нет</td></tr>}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {(has("sections", "by_kind") || has("sections", "by_model")) && (
            <div className="rep-two">
              {has("sections", "by_kind") && (
                <div>
                  <h2>По видам операций</h2>
                  <div className="table-wrap"><table className="tbl">
                    <thead><tr><th>Операция</th><th className="num">Запросов</th><th className="num">Себестоимость</th></tr></thead>
                    <tbody>{rep.by_kind.map((r) => (
                      <tr key={r.kind}><td>{r.name}</td><td className="num">{num(r.calls)}</td><td className="num">{rub(r.cost)}</td></tr>))}
                    </tbody></table></div>
                </div>
              )}
              {has("sections", "by_model") && (
                <div>
                  <h2>По моделям</h2>
                  <div className="table-wrap"><table className="tbl">
                    <thead><tr><th>Модель</th><th className="num">Запросов</th><th className="num">Себестоимость</th><th className="num">Средняя</th></tr></thead>
                    <tbody>{rep.by_model.map((r) => (
                      <tr key={r.model}><td className="mono">{r.model}</td><td className="num">{num(r.calls)}</td>
                        <td className="num">{rub(r.cost)}</td><td className="num hint">{r.avg.toLocaleString("ru-RU")} ₽</td></tr>))}
                    </tbody></table></div>
                </div>
              )}
            </div>
          )}
          {!tiles.length && !sel.sections.length && <div className="empty">Ничего не выбрано — отметьте показатели или разделы выше.</div>}
          <p className="hint">Даты — по московскому времени. CSV выгружает то же, что показано на экране; открывается в Excel.</p>
        </>
      )}
    </section>
  );
}

function Group({ title, items, isOn, onToggle, onAll, disabled }: {
  title: string; items: [string, string][]; isOn: (k: string) => boolean; onToggle: (k: string, on: boolean) => void;
  onAll: (on: boolean) => void; disabled?: boolean;
}) {
  const allOn = items.every(([k]) => isOn(k));
  return (
    <fieldset className={`rep-group ${disabled ? "off" : ""}`} disabled={disabled}>
      <legend>{title} <button type="button" className="link" onClick={() => onAll(!allOn)}>{allOn ? "снять все" : "выбрать все"}</button></legend>
      <div className="rep-checks">
        {items.map(([k, label]) => (
          <label key={k} className={`rep-check ${isOn(k) ? "on" : ""}`}>
            <input type="checkbox" checked={isOn(k)} onChange={(e) => onToggle(k, e.target.checked)} /> {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Kpi({ label, value, hint, strong, warn }: { label: string; value: string; hint?: string; strong?: boolean; warn?: boolean }) {
  return (
    <div className={`kpi ${strong ? "strong" : ""} ${warn ? "warn" : ""}`}>
      <small>{label}</small><b>{value}</b>{hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}
