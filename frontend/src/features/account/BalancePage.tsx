import { isDesktop } from "../../desktop/runtime";
import { useEffect, useState } from "react";
import { authApi } from "../../api/client";
import type { AccountBalance, MyPlan } from "../../api/types";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { Ledger } from "../master/FinancePage";

/** Кабинет: баланс и история списаний. */
export function BalancePage() {
  const ui = useUI();
  const [d, setD] = useState<AccountBalance | null>(null);
  const [plan, setPlan] = useState<MyPlan | null>(null);
  useEffect(() => {
    authApi.balance().then(setD).catch((e) => ui.toast(e.message));
    authApi.me().then((m) => setPlan(m.client?.plan || null)).catch(() => {});
  }, [ui]);
  return (
    <section className="page narrow">
      <div className="page-head"><h1>Тарифы и баланс</h1><span className="spacer" />
        {!isDesktop && <a className="btn" href="/pricing">Все цены</a>}
        {!isDesktop && d?.billing && <a className="btn primary" href="/pricing#packages">Пополнить баланс</a>}</div>
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
          {d.billing && <p>Зарезервировано: {rub(d.reserved ?? 0)} · Доступно: {rub(d.available ?? d.balance ?? 0)}</p>}
          {plan && <PlanCard plan={plan} />}
          {d.prices && d.prices.length > 0 && (
            <>
              <h2>Сколько стоят операции</h2>
              <div className="price-grid">
                {d.prices.map((x) => (
                  <div key={x.what} className="price-card">
                    <small>{x.what}</small>
                    <b>≈ {rub(x.avg)}</b>
                    <span className="hint">в среднем · {x.count} за 90 дней</span>
                  </div>
                ))}
              </div>
              <p className="hint">Цена зависит от пресета: качество, разрешение и модель генерации. «Улучшить до 4K» и «Удалить фон» стоят как правка кадра.</p>
            </>
          )}
          <p className="lead">Каждая генерация, правка и ИИ-проверка списывается сразу после выполнения. Если баланс закончился,
            новые задания не запускаются — уже начатые доделывают текущую попытку. {!isDesktop && <>Пополнить баланс или сменить тариф можно на странице «Цены и оплата».</>}</p>
          <h2>История операций</h2>
          <Ledger rows={d.entries} />
        </>
      )}
    </section>
  );
}

const QN: Record<string, string> = { draft: "Черновик", standard: "Стандарт", premium: "Премиум", custom: "Свой" };
const lim = (v: number | null) => (v === null ? "без ограничений" : v === 0 ? "нет" : String(v));

/** Тариф кабинета и его лимиты. */
function PlanCard({ plan }: { plan: MyPlan }) {
  const l = plan.limits;
  const ended = plan.key !== "start" && plan.effective === "start";
  return (
    <div className="plan-card">
      <div className="plan-card-head">
        <div><small>Тариф</small><b>{plan.name}</b>
          {plan.until && plan.effective !== "start" && <span className="hint"> до {new Date(plan.until).toLocaleDateString("ru-RU")}</span>}
          {ended && <span className="bad-text"> — оплаченный тариф закончился</span>}</div>
        {!isDesktop && <a className="btn" href="/pricing#plans">{plan.effective === "agency" ? "Продлить" : "Сменить тариф"}</a>}
      </div>
      <div className="plan-limits">
        <span>Качество: <b>{l.qualities.map((q) => QN[q] || q).join(", ")}</b></span>
        <span>Генераций одновременно: <b>{l.parallel}</b></span>
        <span>Хранилище: <b>{l.storage_gb} ГБ</b></span>
        <span>Проекты: <b>{lim(l.projects)}</b></span>
        <span>Свои пресеты: <b>{lim(l.presets)}</b></span>
        <span>Свои модели-люди: <b>{lim(l.personas)}</b></span>
        <span>Оформление по примеру: <b>{lim(l.styles)}</b></span>
        <span>Ручной план и модель на блок: <b>{l.manual_plan ? "да" : "нет"}</b></span>
      </div>
    </div>
  );
}

