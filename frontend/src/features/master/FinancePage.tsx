import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { FinanceView, LedgerEntry, TopupRequest } from "../../api/types";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { PlansEditor } from "./PlansEditor";

/** Мастер: деньги сервиса — выручка (списания с балансов), себестоимость Polza, пополнения, журнал операций. */
export function FinancePage() {
  const ui = useUI();
  const [data, setData] = useState<FinanceView | null>(null);
  const [kind, setKind] = useState<"" | "charge" | "topup">("");
  const [client, setClient] = useState("");
  const [requests, setRequests] = useState<TopupRequest[]>([]);
  const [plansOpen, setPlansOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await adminApi.finance());
      setRequests((await adminApi.topups()).items);
    } catch (e) {
      ui.toast((e as Error).message);
    }
  }, [ui]);
  useEffect(() => {
    load();
  }, [load]);

  const clients = data ? [...new Set(data.entries.map((e) => e.client || ""))].filter(Boolean).sort() : [];
  const rows = (data?.entries || []).filter((e) => (!kind || (kind === "topup" ? e.kind !== "charge" : e.kind === "charge"))
    && (!client || e.client === client));
  const s = data?.summary;
  const pending = requests.filter((r) => r.status === "new");
  const resolve = async (r: TopupRequest, action: "paid" | "cancel") => {
    const total = r.amount + r.bonus;
    const ok = await ui.confirm(action === "paid"
      ? { title: `Зачислить заявку №${r.id}?`, text: `«${r.client}» оплатил ${rub(r.amount)} (${r.method_name}). На баланс поступит ${rub(total)}${r.bonus ? `, из них бонус ${rub(r.bonus)}` : ""}.`
          + (r.plan_name ? ` Тариф «${r.plan_name}» включится или продлится на ${r.months === 12 ? "12 месяцев" : "1 месяц"}.` : ""), ok: "Зачислить" }
      : { title: `Отклонить заявку №${r.id}?`, text: `«${r.client}», ${rub(r.amount)}. Баланс не изменится.`, ok: "Отклонить" });
    if (!ok) return;
    try {
      await adminApi.resolveTopup(r.id, action);
      ui.toast(action === "paid" ? `Зачислено ${rub(total)}` : "Заявка отклонена");
      await load();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  return (
    <section className="page">
      <div className="page-head"><h1>Финансы</h1><span className="spacer" />
        <button onClick={() => setPlansOpen(true)}>Условия тарифов</button><button onClick={load}>Обновить</button></div>
      {plansOpen && <PlansEditor onClose={() => setPlansOpen(false)} />}
      {s && (
        <div className="kpis">
          <Kpi label="Списано с пользователей за месяц" value={rub(s.revenue_month)} />
          <Kpi label="Себестоимость Polza за месяц" value={rub(s.cost_month)} />
          <Kpi label="Наценка за месяц" value={rub(s.margin_month)} strong />
          <Kpi label="Пополнения за месяц" value={rub(s.topups_month)} />
          <Kpi label="Остаток на балансах" value={rub(s.balances)} />
        </div>
      )}
      {pending.length > 0 && (
        <div className="panel topup-reqs">
          <div className="row"><b>Заявки на пополнение</b><span className="tab-badge">{pending.length}</span>
            <span className="hint">— после оплаты нажмите «Зачислить»: сумма и бонус пакета поступят на баланс пользователя</span></div>
          <div className="table-wrap"><table className="tbl">
            <thead><tr><th>№</th><th>Когда</th><th>Пользователь</th><th className="num">Сумма</th><th className="num">Бонус</th><th>Способ</th><th>Комментарий</th><th /></tr></thead>
            <tbody>{pending.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td className="hint nowrap">{r.created ? new Date(r.created).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</td>
                <td>{r.client}<div className="hint">{r.user}</div></td>
                <td className="num"><b>{rub(r.amount)}</b></td><td className="num hint">{r.bonus ? rub(r.bonus) : "—"}</td>
                <td>{r.method_name}</td>
                <td className="hint">{r.plan_name && <b className="plan-chip">Тариф «{r.plan_name}» · {r.months === 12 ? "год" : "месяц"}</b>} {r.note}</td>
                <td className="nowrap"><button className="primary small" onClick={() => resolve(r, "paid")}>Зачислить</button>{" "}
                  <button className="small" onClick={() => resolve(r, "cancel")}>Отклонить</button></td>
              </tr>))}
            </tbody></table></div>
        </div>
      )}
      <div className="row nowrap mb10">
        <span className="seg">
          <button className={kind === "" ? "on" : ""} onClick={() => setKind("")}>Все операции</button>
          <button className={kind === "charge" ? "on" : ""} onClick={() => setKind("charge")}>Списания</button>
          <button className={kind === "topup" ? "on" : ""} onClick={() => setKind("topup")}>Пополнения</button>
        </span>
        <select value={client} onChange={(e) => setClient(e.target.value)}>
          <option value="">Все пользователи</option>
          {clients.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <Ledger rows={rows} master />
    </section>
  );
}

function Kpi({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return <div className={`kpi ${strong ? "strong" : ""}`}><small>{label}</small><b>{value}</b></div>;
}

export function Ledger({ rows, master }: { rows: LedgerEntry[]; master?: boolean }) {
  if (!rows.length) return <div className="empty">Операций пока нет</div>;
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead><tr><th>Когда</th>{master && <th>Пользователь</th>}<th>Операция</th><th className="num">Сумма</th>
          {master && <th className="num">Себест.</th>}<th className="num">Остаток</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id}>
              <td className="hint nowrap">{e.created ? new Date(e.created).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</td>
              {master && <td>{e.client}</td>}
              <td>{e.what || (e.kind === "topup" ? "пополнение" : "")}</td>
              <td className={`num ${e.amount > 0 ? "plus" : ""}`}>{e.amount > 0 ? "+" : ""}{rub(e.amount)}</td>
              {master && <td className="num hint">{e.kind === "charge" ? rub(e.cost) : ""}</td>}
              <td className="num">{rub(e.balance_after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
