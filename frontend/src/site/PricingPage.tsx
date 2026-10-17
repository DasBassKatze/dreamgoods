import { useCallback, useEffect, useState } from "react";
import { authApi, publicApi } from "../api/client";
import type { PriceList, TopupRequest } from "../api/types";
import { Calculator, useReveal } from "./Interactive";
import { SiteLayout } from "./SiteLayout";

const rub = (v: number) => `${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
const METHODS: [TopupRequest["method"], string, string][] = [
  ["sbp", "СБП", "перевод по QR-коду из приложения банка"],
  ["card", "Банковская карта", "карты российских банков"],
  ["invoice", "Счёт для компании или ИП", "оплата с расчётного счёта"],
];
const STATUS: Record<TopupRequest["status"], string> = { new: "ждёт оплаты", paid: "зачислено", cancelled: "отменена" };

/** Страница «Цены и оплата»: стоимость кадров и операций, пакеты пополнения и заявка на пополнение. */
export function PricingPage() {
  const [p, setP] = useState<PriceList | null>(null);
  const [amount, setAmount] = useState<number>(() => {
    const a = Number(new URLSearchParams(window.location.search).get("amount"));
    return a > 0 ? a : 1500;
  });
  useReveal();
  const [method, setMethod] = useState<TopupRequest["method"]>("sbp");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState<TopupRequest | null>(null);
  const [mine, setMine] = useState<TopupRequest[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const prices = await publicApi.prices();
      setP(prices);
      if (prices.billing) setMine((await authApi.topups()).items);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  // переход по ссылке «/pricing#packages» — прокрутить к пакетам, когда цены загрузились
  useEffect(() => {
    if (p && window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [!!p]); // eslint-disable-line react-hooks/exhaustive-deps

  const bonusRate = p ? p.packages.reduce((r, k) => (amount >= k.amount ? k.bonus_rate : r), 0) : 0;
  const standard = p?.tiers.find((t) => t.key === "standard")?.price || 0;
  const valid = !!p && amount >= p.min_topup && amount <= p.max_topup;

  const pick = (a: number) => {
    setAmount(a);
    document.getElementById("topup")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!p?.signed_in) {
      window.location.href = "/studio";
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const r = await authApi.createTopup(amount, method, note);
      setSent(r);
      setNote("");
      setMine((await authApi.topups()).items);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SiteLayout page="pricing">
      <section className="sec page-top">
        <div className="site-wrap">
          <span className="eyebrow">Цены и оплата</span>
          <h1>Платите только за готовые кадры</h1>
          <p className="sec-lead">Без подписки и абонентской платы. Баланс в рублях не сгорает. Точная цена видна перед каждым
            запуском, списание — после выполнения.</p>
          {p?.balance != null && <p className="balance-note">На вашем балансе: <b>{rub(p.balance)}</b></p>}
        </div>
      </section>

      <section className="sec tight">
        <div className="site-wrap">
          <h2>Стоимость кадра</h2>
          <div className="tier-grid">
            {(p?.tiers || []).map((t) => (
              <article key={t.key} className={`tier ${t.key === "standard" ? "featured" : ""}`} data-reveal>
                <header><h3>{t.name}</h3>{t.key === "standard" && <span className="pcard-tag">Популярный</span>}</header>
                <div className="pcard-price">{rub(t.price)}<small> / кадр</small></div>
                <ul>
                  <li>{t.model}, {t.resolution}</li>
                  <li>{t.qc ? "ИИ-проверка и переделка брака" : "без ИИ-проверки"}</li>
                  <li className="muted">{t.note}</li>
                </ul>
              </article>
            ))}
            {!p && !err && <p className="muted">Загружаю цены…</p>}
          </div>
          <p className="fine">Цена кадра — средняя: в неё уже входят переделки брака и ИИ-проверка. Списывается фактическая
            стоимость каждой операции, поэтому отдельный кадр может выйти чуть дешевле или дороже.</p>

          <h2 className="mt" data-reveal>Сколько выйдет ваша коллекция</h2>
          <div data-reveal><Calculator prices={p} compact /></div>

          <h2 className="mt" data-reveal>Операции с готовыми кадрами</h2>
          <div className="ops">
            {(p?.ops || []).map((o) => (
              <div key={o.key} className="op"><div><b>{o.name}</b><span className="muted">{o.note}</span></div><span className="op-price">{rub(o.price)}</span></div>
            ))}
          </div>
        </div>
      </section>

      <section className="sec alt" id="packages">
        <div className="site-wrap">
          <h2>Пополнение баланса</h2>
          <p className="sec-lead">Чем больше пакет, тем больше бонус к сумме.</p>
          <div className="pack-grid">
            {(p?.packages || []).map((k) => (
              <button key={k.amount} type="button" className={`pack ${amount === k.amount ? "on" : ""}`} onClick={() => pick(k.amount)} data-reveal>
                <span className="pack-sum">{rub(k.amount)}</span>
                <span className="pack-bonus">{k.bonus_rate ? `+${Math.round(k.bonus_rate * 100)}% бонус` : "без бонуса"}</span>
                <span className="muted">≈ {k.frames.toLocaleString("ru-RU")} кадров «Стандарт»</span>
              </button>
            ))}
          </div>

          <form className="topup" id="topup" onSubmit={submit}>
            <div className="topup-row">
              <label className="tf"><span>Сумма, ₽</span>
                <input type="number" min={p?.min_topup} max={p?.max_topup} step={100} value={amount}
                  onChange={(e) => setAmount(Math.max(0, +e.target.value || 0))} /></label>
              <div className="topup-sum">
                {bonusRate > 0 && <span>Бонус +{Math.round(bonusRate * 100)}%: <b>{rub(Math.round(amount * bonusRate * 100) / 100)}</b></span>}
                <span>На баланс поступит <b>{rub(Math.round(amount * (1 + bonusRate) * 100) / 100)}</b>
                  {standard ? <> ≈ {Math.floor((amount * (1 + bonusRate)) / standard).toLocaleString("ru-RU")} кадров «Стандарт»</> : null}</span>
              </div>
            </div>
            <fieldset className="methods">
              <legend>Способ оплаты</legend>
              {METHODS.map(([k, t, d]) => (
                <label key={k} className={`method ${method === k ? "on" : ""}`}>
                  <input type="radio" name="method" checked={method === k} onChange={() => setMethod(k)} />
                  <span><b>{t}</b><small>{d}</small></span>
                </label>
              ))}
            </fieldset>
            {method === "invoice" && (
              <label className="tf"><span>Реквизиты для счёта</span>
                <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="Название, ИНН, КПП (для компаний), почта для счёта" /></label>
            )}
            {method !== "invoice" && (
              <label className="tf"><span>Комментарий (необязательно)</span>
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Как с вами удобнее связаться" /></label>
            )}
            {err && <div className="err">{err}</div>}
            {sent && <div className="okmsg">Заявка №{sent.id} принята: {rub(sent.amount)}{sent.bonus ? ` + бонус ${rub(sent.bonus)}` : ""}.
              Мы пришлём реквизиты для оплаты, и сразу после оплаты деньги поступят на баланс.</div>}
            <div className="topup-foot">
              <button className="site-btn primary big" disabled={busy || !valid || (p?.signed_in && !p.billing)}>
                {!p?.signed_in ? "Войти и пополнить" : busy ? "Отправляю…" : "Пополнить баланс"}
              </button>
              <span className="muted">
                {!valid && p ? `Сумма — от ${rub(p.min_topup)} до ${rub(p.max_topup)}.` :
                  p?.signed_in && !p.billing ? "Для вашего кабинета пополнение не требуется." :
                  "Онлайн-оплата подключается; пока после заявки мы пришлём реквизиты или ссылку на оплату."}
              </span>
            </div>
          </form>

          {mine.length > 0 && (
            <div className="my-topups">
              <h3>Ваши заявки</h3>
              <table>
                <thead><tr><th>№</th><th>Дата</th><th>Сумма</th><th>Бонус</th><th>Способ</th><th>Статус</th></tr></thead>
                <tbody>{mine.map((r) => (
                  <tr key={r.id}><td>{r.id}</td><td>{r.created ? new Date(r.created).toLocaleDateString("ru-RU") : ""}</td>
                    <td>{rub(r.amount)}</td><td>{r.bonus ? rub(r.bonus) : "—"}</td><td>{r.method_name}</td>
                    <td><span className={`st st-${r.status}`}>{STATUS[r.status]}</span></td></tr>))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="sec">
        <div className="site-wrap narrow">
          <h2>Вопросы об оплате</h2>
          <div className="faq">
            <details><summary>Сгорают ли деньги на балансе?</summary><p>Нет, баланс бессрочный.</p></details>
            <details><summary>Когда списываются деньги?</summary><p>После того как операция выполнена: кадр снят, правка сделана, проверка пройдена.
              Если генерация завершилась ошибкой на стороне сервиса, она не оплачивается.</p></details>
            <details><summary>Можно оплатить по счёту?</summary><p>Да — выберите «Счёт для компании или ИП» и укажите реквизиты. Счёт придёт на почту.</p></details>
            <details><summary>Есть ли цены для больших объёмов?</summary><p>Да, для больших объёмов обсудим индивидуальные условия — оставьте заявку
              с комментарием.</p></details>
          </div>
        </div>
      </section>
    </SiteLayout>
  );
}
