import { useEffect, useState } from "react";
import { authApi } from "../../api/client";
import type { AccountBalance } from "../../api/types";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { Ledger } from "../master/FinancePage";

/** Кабинет: баланс и история списаний. */
export function BalancePage() {
  const ui = useUI();
  const [d, setD] = useState<AccountBalance | null>(null);
  useEffect(() => {
    authApi.balance().then(setD).catch((e) => ui.toast(e.message));
  }, [ui]);
  return (
    <section className="page narrow">
      <div className="page-head"><h1>Баланс</h1></div>
      {!d ? <div className="empty">Загрузка…</div> : (
        <>
          <div className="balance-hero">
            <div>
              <small>На счёте</small>
              <b className={d.billing && (d.balance ?? 0) <= 0 ? "bad-text" : ""}>{d.billing ? rub(d.balance) : "без ограничений"}</b>
            </div>
            <div>
              <small>Потрачено в этом месяце</small>
              <b>{rub(d.spent_month)}</b>
            </div>
          </div>
          <p className="lead">Каждая генерация, правка и ИИ-проверка списывается сразу после выполнения. Если баланс закончился,
            новые задания не запускаются — уже начатые доделывают текущую попытку. Пополнить баланс можно у администратора сервиса.</p>
          <h2>История операций</h2>
          <Ledger rows={d.entries} />
        </>
      )}
    </section>
  );
}
