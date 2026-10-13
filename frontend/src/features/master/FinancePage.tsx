import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { FinanceView, LedgerEntry } from "../../api/types";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";

/** Мастер: деньги сервиса — выручка (списания с балансов), себестоимость Polza, пополнения, журнал операций. */
export function FinancePage() {
  const ui = useUI();
  const [data, setData] = useState<FinanceView | null>(null);
  const [kind, setKind] = useState<"" | "charge" | "topup">("");
  const [client, setClient] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await adminApi.finance());
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

  return (
    <section className="page">
      <div className="page-head"><h1>Финансы</h1><span className="spacer" /><button onClick={load}>Обновить</button></div>
      {s && (
        <div className="kpis">
          <Kpi label="Списано с пользователей за месяц" value={rub(s.revenue_month)} />
          <Kpi label="Себестоимость Polza за месяц" value={rub(s.cost_month)} />
          <Kpi label="Наценка за месяц" value={rub(s.margin_month)} strong />
          <Kpi label="Пополнения за месяц" value={rub(s.topups_month)} />
          <Kpi label="Остаток на балансах" value={rub(s.balances)} />
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
