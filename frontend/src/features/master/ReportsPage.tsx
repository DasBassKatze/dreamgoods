import { useCallback, useEffect, useMemo, useState } from "react";
import { adminApi } from "../../api/client";
import type { ServiceReport } from "../../api/types";
import { useUI } from "../../components/ui";
import { Icon } from "../../layout/Icon";
import { rub } from "../../lib/format";

type Preset = "month" | "prev-month" | "quarter" | "prev-quarter" | "year" | "prev-year" | "custom";
const PRESETS: [Preset, string][] = [
  ["month", "Этот месяц"], ["prev-month", "Прошлый месяц"], ["quarter", "Этот квартал"], ["prev-quarter", "Прошлый квартал"],
  ["year", "Этот год"], ["prev-year", "Прошлый год"], ["custom", "Свой период"],
];
const RATES: [number, string][] = [[0.06, "6% — УСН «Доходы» / НПД с ИП и компаний"], [0.04, "4% — НПД с физлиц"],
  [0.08, "8% — АУСН «Доходы»"], [0, "не показывать"]];

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function range(p: Preset): [string, string] {
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth(), q = Math.floor(m / 3);
  switch (p) {
    case "prev-month": return [iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))];
    case "quarter": return [iso(new Date(y, q * 3, 1)), iso(now)];
    case "prev-quarter": return [iso(new Date(y, q * 3 - 3, 1)), iso(new Date(y, q * 3, 0))];
    case "year": return [iso(new Date(y, 0, 1)), iso(now)];
    case "prev-year": return [iso(new Date(y - 1, 0, 1)), iso(new Date(y - 1, 11, 31))];
    default: return [iso(new Date(y, m, 1)), iso(now)];
  }
}

const fmtDay = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
const fmtDate = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
const num = (v: number) => v.toLocaleString("ru-RU");

/** Мастер: отчёт сервиса за выбранный период — деньги клиентов, себестоимость Polza, наценка и объём работы. */
export function ReportsPage() {
  const ui = useUI();
  const [preset, setPreset] = useState<Preset>("month");
  const [[from, to], setRange] = useState<[string, string]>(range("month"));
  const [client, setClient] = useState<number | null>(null);
  const [rate, setRate] = useState(0.06);
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

  const s = rep?.summary;
  const maxDay = Math.max(1, ...(rep?.by_day || []).map((d) => Math.max(d.charge, d.cost, d.topup)));

  return (
    <section className="page reports">
      <div className="page-head">
        <h1>Отчёты</h1>
        {rep && <span className="hint">{fmtDate(rep.from)} — {fmtDate(rep.to)}</span>}
        <span className="spacer" />
        <button onClick={load} disabled={loading}>{loading ? "Считаю…" : "Обновить"}</button>
        <a className="btn primary" href={adminApi.reportCsvUrl(q)}><Icon name="download" size={16} /> Скачать CSV</a>
      </div>

      <div className="rep-filters">
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
      </div>

      {!s ? <div className="empty">{loading ? "Считаю отчёт…" : "Нет данных"}</div> : (
        <>
          <div className="kpis">
            <Kpi label="Поступило от клиентов (пополнения)" value={rub(s.topups)} hint="Доход для налога на УСН и НПД — в день поступления денег" strong />
            <Kpi label="Списано с балансов за услуги" value={rub(s.charged)} hint={`${num(s.clients_paying)} платящих пользователей`} />
            <Kpi label="Наценка по списаниям" value={rub(s.margin)} hint={s.markup ? `×${s.markup.toLocaleString("ru-RU")} к себестоимости` : ""} strong />
            <Kpi label="Весь расход Polza" value={rub(s.polza)} hint={s.polza_unbilled > 0 ? `${rub(s.polza_unbilled)} — без оплаты клиентом` : ""} />
            <Kpi label="Итог: списано − расход Polza" value={rub(s.result)} warn={s.result < 0} />
            <Kpi label="Остаток на балансах на конец" value={rub(s.balances_end)} hint="Деньги клиентов, ещё не потраченные" />
            <Kpi label="Изображений" value={num(s.images)} hint={`из них правок ${num(s.edits)} · проверок ${num(s.checks)}`} />
            <Kpi label="Ошибок заданий" value={num(s.errors)} warn={s.errors > 0} />
            {s.usn_rate > 0 && <Kpi label={`Налог ${s.usn_rate * 100}% с пополнений (оценка)`} value={rub(s.usn_tax)}
              hint="Без вычета страховых взносов" />}
          </div>
          {s.polza_unbilled > 0 && (
            <p className="hint">Расход Polza без оплаты клиентом — генерации мастера и кабинетов без внутреннего баланса.
              Он уменьшает итог, но не попадает в списания.</p>
          )}

          {rep.by_day.length > 0 && (
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

          <h2>По пользователям</h2>
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>Пользователь</th><th className="num">Пополнения</th><th className="num">Списано</th>
                <th className="num">Себест. списаний</th><th className="num">Наценка</th><th className="num">Весь расход Polza</th>
                <th className="num">Изображений</th><th className="num">Остаток</th></tr></thead>
              <tbody>
                {rep.clients.map((r) => (
                  <tr key={r.client_id ?? "none"}>
                    <td>{r.client}{!r.billing && r.client_id != null && <span className="hint"> · без баланса</span>}</td>
                    <td className="num">{rub(r.topup)}</td><td className="num">{rub(r.charged)}</td>
                    <td className="num hint">{rub(r.charged_cost)}</td><td className="num"><b>{rub(r.margin)}</b></td>
                    <td className="num">{rub(r.polza)}</td>
                    <td className="num">{num(r.images)}{r.edits ? <span className="hint"> / {num(r.edits)} правок</span> : null}</td>
                    <td className="num">{r.balance_end == null ? "—" : rub(r.balance_end)}</td>
                  </tr>
                ))}
                {!rep.clients.length && <tr><td colSpan={8} className="hint">За период операций нет</td></tr>}
              </tbody>
            </table>
          </div>

          <div className="rep-two">
            <div>
              <h2>По видам операций</h2>
              <div className="table-wrap"><table className="tbl">
                <thead><tr><th>Операция</th><th className="num">Запросов</th><th className="num">Себестоимость</th></tr></thead>
                <tbody>{rep.by_kind.map((r) => (
                  <tr key={r.kind}><td>{r.name}</td><td className="num">{num(r.calls)}</td><td className="num">{rub(r.cost)}</td></tr>))}
                </tbody></table></div>
            </div>
            <div>
              <h2>По моделям</h2>
              <div className="table-wrap"><table className="tbl">
                <thead><tr><th>Модель</th><th className="num">Запросов</th><th className="num">Себестоимость</th><th className="num">Средняя</th></tr></thead>
                <tbody>{rep.by_model.map((r) => (
                  <tr key={r.model}><td className="mono">{r.model}</td><td className="num">{num(r.calls)}</td>
                    <td className="num">{rub(r.cost)}</td><td className="num hint">{r.avg.toLocaleString("ru-RU")} ₽</td></tr>))}
                </tbody></table></div>
            </div>
          </div>
          <p className="hint">Даты — по московскому времени. CSV открывается в Excel: разделы идут друг под другом.</p>
        </>
      )}
    </section>
  );
}

function Kpi({ label, value, hint, strong, warn }: { label: string; value: string; hint?: string; strong?: boolean; warn?: boolean }) {
  return (
    <div className={`kpi ${strong ? "strong" : ""} ${warn ? "warn" : ""}`}>
      <small>{label}</small><b>{value}</b>{hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}
