import { useState } from "react";
import { authApi } from "../../api/client";
import type { Me } from "../../api/types";
import { useUI } from "../../components/ui";
import { ConsentsSection } from "./ConsentsSection";

/** Учётная запись: кто вошёл, смена пароля, выход. */
export function AccountPage({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const ui = useUI();
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await authApi.password(old, next);
      setOld("");
      setNext("");
      ui.toast("Пароль изменён. На других устройствах нужно будет войти заново");
    } catch (err) {
      ui.toast((err as Error).message);
    }
  };
  return (
    <section className="page narrow">
      <div className="page-head"><h1>Учётная запись</h1><span className="spacer" /><button onClick={onLogout}>Выйти</button></div>
      <dl className="facts">
        <dt>Имя</dt><dd>{me.name}</dd>
        <dt>Логин</dt><dd>{me.email}</dd>
        <dt>Доступ</dt><dd>{me.role === "master" ? "Мастер-аккаунт: все кабинеты и управление сервисом" : "Личный кабинет"}</dd>
      </dl>
      <h2>Сменить пароль</h2>
      <form className="form grid narrow-form" onSubmit={save}>
        <label className="form-label" htmlFor="p-old">Текущий пароль</label>
        <input id="p-old" type="password" autoComplete="current-password" value={old} onChange={(e) => setOld(e.target.value)} />
        <label className="form-label" htmlFor="p-new">Новый пароль</label>
        <input id="p-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        <span />
        <div><button className="primary" disabled={!old || next.length < 6}>Сменить пароль</button>
          <span className="hint"> не короче 6 символов</span></div>
      </form>
      {me.role !== "master" && <ConsentsSection />}
    </section>
  );
}
