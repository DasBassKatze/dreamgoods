import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { PolzaKeyView, SiteUser, UsersListing } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "ещё не входил";

const genPassword = () => {
  const a = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from(crypto.getRandomValues(new Uint32Array(10)), (x) => a[x % a.length]).join("");
};

/** Мастер: пользователи сайта, их кабинеты и балансы. */
export function UsersPage() {
  const ui = useUI();
  const [data, setData] = useState<UsersListing | null>(null);
  const [keys, setKeys] = useState<PolzaKeyView[]>([]);
  const [planNames, setPlanNames] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<SiteUser | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      const [u, k, pl] = await Promise.all([adminApi.users(), adminApi.keys(), adminApi.plans().catch(() => null)]);
      if (pl) setPlanNames(Object.fromEntries(pl.plans.map((x) => [x.key, x.name])));
      setData(u);
      setKeys(k.keys);
    } catch (e) {
      ui.toast((e as Error).message);
    }
  }, [ui]);
  useEffect(() => {
    load();
  }, [load]);

  const topup = async (u: SiteUser) => {
    if (!u.client) return;
    const v = await ui.ask({ title: `Пополнить баланс: ${u.name}`, ok: "Пополнить", fields: [
      { key: "amount", label: "Сумма, ₽ (минус — списать)", value: "1000" },
      { key: "note", label: "Комментарий (видит пользователь)", value: "пополнение" }] });
    if (!v) return;
    const amount = parseFloat(v.amount.replace(",", "."));
    if (!amount) return ui.toast("Укажите сумму");
    try {
      const r = await adminApi.topup(u.client.id, amount, v.note);
      ui.toast(`Баланс ${u.name}: ${rub(r.balance)}`);
      load();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  const markup = async () => {
    const v = await ui.ask({ title: "Общая наценка", ok: "Сохранить", fields: [
      { key: "m", label: "Множитель к себестоимости Polza (1.5 = +50%)", value: String(data?.markup ?? 1) }] });
    if (!v) return;
    try {
      await adminApi.setMarkup(parseFloat(v.m.replace(",", ".")) || 1);
      load();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  return (
    <section className="page">
      <div className="page-head">
        <h1>Пользователи</h1>
        <span className="spacer" />
        <button onClick={markup} title="Применяется ко всем, у кого не задана своя">Наценка по умолчанию: ×{data?.markup ?? 1}</button>
        <button className="primary" onClick={() => setEditing("new")}>Добавить пользователя</button>
      </div>
      <p className="lead">Каждый пользователь работает в своём кабинете и видит только свои проекты. Генерации списываются
        с его баланса по себестоимости Polza × наценка.</p>
      {!data ? <div className="empty">Загрузка…</div> : (
        <div className="table-wrap">
          <table className="tbl users">
            <thead><tr><th>Пользователь</th><th>Тариф</th><th className="num">Баланс</th><th className="num">Наценка</th><th>Ключ Polza</th>
              <th className="num">За месяц: списано / себест.</th><th>Последний вход</th><th /></tr></thead>
            <tbody>
              {data.users.map((u) => (
                <tr key={u.id} className={u.active ? "" : "off"}>
                  <td>
                    <button className="link strong" onClick={() => setEditing(u)}>{u.name}</button>
                    <div className="hint">{u.email}{u.role === "master" ? " · мастер" : ""}{!u.active && " · заблокирован"}
                      {u.client && ` · проектов ${u.client.projects}`}</div>
                  </td>
                  <td>{u.client?.billing ? (
                    <>{planNames[u.client.plan_effective] || u.client.plan_effective}
                      {u.client.plan !== "start" && u.client.plan_until && (
                        <div className={`hint ${u.client.plan_effective === "start" ? "bad-text" : ""}`}>
                          {u.client.plan_effective === "start" ? `${planNames[u.client.plan] || u.client.plan} закончился ` : "до "}
                          {new Date(u.client.plan_until).toLocaleDateString("ru-RU")}</div>)}</>
                  ) : <span className="hint">без лимитов</span>}</td>
                  <td className="num">{u.client ? (
                    <span className={u.client.billing && u.client.balance <= 0 ? "bad-text" : ""}>
                      {u.client.billing ? rub(u.client.balance) : "без баланса"}</span>) : "—"}</td>
                  <td className="num">{u.client ? `×${u.client.markup_effective}${u.client.markup == null ? "" : " (своя)"}` : "—"}</td>
                  <td>{u.client ? (u.client.key_name || <span className="hint">общий пул</span>) : "—"}</td>
                  <td className="num">{u.client ? `${rub(u.client.charged_month)} / ${rub(u.client.cost_month)}` : "—"}</td>
                  <td className="hint">{when(u.last_login)}</td>
                  <td className="actions">{u.client?.billing && <button onClick={() => topup(u)}>Пополнить</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && data && (
        <UserEditor user={editing === "new" ? null : editing} keys={keys} free={data.unassigned_clients} planNames={planNames}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}
    </section>
  );
}

function UserEditor({ user, keys, free, planNames, onClose, onSaved }: {
  user: SiteUser | null; keys: PolzaKeyView[]; free: UsersListing["unassigned_clients"]; planNames: Record<string, string>;
  onClose: () => void; onSaved: () => void;
}) {
  const ui = useUI();
  const [f, setF] = useState({
    email: user?.email || "", name: user?.name || "", password: user ? "" : genPassword(),
    role: user?.role || "user", balance: "0", markup: user?.client?.markup == null ? "" : String(user.client.markup),
    key_id: user?.client?.key_id || 0, client_id: 0, active: user?.active ?? true, billing: user?.client?.billing ?? true,
    plan: user?.client?.plan_effective || "start", plan_months: 0, plan_until: "",
  });
  const set = (k: keyof typeof f, v: string | number | boolean) => setF({ ...f, [k]: v });

  const save = async () => {
    try {
      if (user) {
        const planChanged = f.plan !== (user.client?.plan_effective || "start") || f.plan_months > 0 || !!f.plan_until;
        await adminApi.updateUser(user.id, { name: f.name, email: f.email, password: f.password || undefined, active: f.active,
          markup: f.markup === "" ? null : parseFloat(f.markup.replace(",", ".")), key_id: f.key_id, billing: f.billing,
          ...(user.client && planChanged ? { plan: f.plan, plan_months: f.plan_months || (f.plan_until ? 0 : 1),
            plan_until: f.plan_until || null } : {}) });
        ui.toast("Сохранено");
      } else {
        await adminApi.createUser({ email: f.email, name: f.name, password: f.password, role: f.role,
          balance: parseFloat(f.balance.replace(",", ".")) || 0, markup: f.markup === "" ? null : parseFloat(f.markup.replace(",", ".")),
          client_id: f.client_id || null, billing: f.billing });
        await navigator.clipboard?.writeText(`Вход: ${location.origin}\nЛогин: ${f.email}\nПароль: ${f.password}`).catch(() => {});
        ui.toast("Пользователь создан — данные для входа скопированы", 5000);
      }
      onSaved();
    } catch (e) {
      ui.toast((e as Error).message, 5000);
    }
  };

  const isUser = f.role === "user";
  return (
    <Modal title={user ? `Пользователь: ${user.name}` : "Новый пользователь"} width={620} onClose={onClose}
      footer={<><span className="spacer" /><button onClick={onClose}>Отмена</button>
        <button className="primary" disabled={!f.email || (!user && f.password.length < 6)} onClick={save}>
          {user ? "Сохранить" : "Создать"}</button></>}>
      <div className="form grid">
        <label className="form-label" htmlFor="u-email">Логин (почта)</label>
        <input id="u-email" type="text" value={f.email} onChange={(e) => set("email", e.target.value)} />
        <label className="form-label" htmlFor="u-name">Имя или магазин</label>
        <input id="u-name" type="text" value={f.name} onChange={(e) => set("name", e.target.value)} />
        <label className="form-label" htmlFor="u-pass">{user ? "Новый пароль" : "Пароль"}</label>
        <div className="row nowrap">
          <input id="u-pass" type="text" value={f.password} placeholder={user ? "оставьте пустым, чтобы не менять" : ""}
            onChange={(e) => set("password", e.target.value)} />
          <button onClick={() => set("password", genPassword())}>Придумать</button>
        </div>
        {!user && (
          <>
            <label className="form-label" htmlFor="u-role">Роль</label>
            <select id="u-role" value={f.role} onChange={(e) => set("role", e.target.value)}>
              <option value="user">Пользователь — свой кабинет</option>
              <option value="master">Мастер — управляет сервисом</option>
            </select>
          </>
        )}
        {isUser && !user && free.length > 0 && (
          <>
            <label className="form-label" htmlFor="u-client">Кабинет</label>
            <select id="u-client" value={f.client_id} onChange={(e) => set("client_id", +e.target.value)}>
              <option value={0}>Новый, пустой</option>
              {free.map((c) => <option key={c.id} value={c.id}>Отдать готовый: {c.name} ({c.projects} проект.)</option>)}
            </select>
          </>
        )}
        {isUser && (
          <>
            <label className="form-label">Оплата</label>
            <label className="check"><input type="checkbox" checked={f.billing} onChange={(e) => set("billing", e.target.checked)} />
              {" "}списывать генерации с баланса</label>
            {!user && f.billing && (
              <>
                <label className="form-label" htmlFor="u-bal">Стартовый баланс, ₽</label>
                <input id="u-bal" type="text" value={f.balance} onChange={(e) => set("balance", e.target.value)} />
              </>
            )}
            {user?.client && f.billing && (
              <>
                <label className="form-label" htmlFor="u-plan">Тариф</label>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                    <select id="u-plan" value={f.plan} onChange={(e) => set("plan", e.target.value)}>
                      {Object.entries(planNames).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
                    </select>
                    {f.plan !== "start" && (
                      <select value={f.plan_months} onChange={(e) => setF({ ...f, plan_months: +e.target.value, plan_until: "" })}
                        aria-label="Срок">
                        <option value={0}>срок не менять</option>
                        {[1, 3, 6, 12].map((m) => <option key={m} value={m}>+{m} мес.</option>)}
                      </select>
                    )}
                    {f.plan !== "start" && (
                      <input type="date" value={f.plan_until} aria-label="До даты" title="или до даты" style={{ width: 150 }}
                        onChange={(e) => setF({ ...f, plan_until: e.target.value, plan_months: 0 })} />
                    )}
                  </div>
                  <span className="hint">{user.client.plan !== "start" && user.client.plan_until
                    ? `сейчас: ${planNames[user.client.plan] || user.client.plan} до ${new Date(user.client.plan_until).toLocaleDateString("ru-RU")}. `
                    : ""}Новый тариф без срока подключается на 1 месяц; оплаченная заявка на тариф продлевает его сама.</span>
                </div>
              </>
            )}
            <label className="form-label" htmlFor="u-markup">Своя наценка</label>
            <input id="u-markup" type="text" placeholder="пусто — общая" value={f.markup} onChange={(e) => set("markup", e.target.value)} />
            <label className="form-label" htmlFor="u-key">Ключ Polza</label>
            <select id="u-key" value={f.key_id} onChange={(e) => set("key_id", +e.target.value)}>
              <option value={0}>Общий пул ключей</option>
              {keys.map((k) => <option key={k.id} value={k.id} disabled={!k.active}>{k.name} ({k.mask}){k.active ? "" : " — выключен"}</option>)}
            </select>
          </>
        )}
        {user && (
          <>
            <label className="form-label">Доступ</label>
            <label className="check"><input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} />
              {" "}может входить на сайт</label>
          </>
        )}
      </div>
      {!user && <p className="hint mt12">После создания логин и пароль скопируются — отправьте их пользователю.</p>}
    </Modal>
  );
}
