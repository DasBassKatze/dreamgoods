import { useState } from "react";
import { authApi } from "../../api/client";
import type { Me } from "../../api/types";
import { SiteFooter } from "../../layout/SiteFooter";

/** Вход. Регистрации нет: учётные записи заводит администратор сервиса. */
export function LoginPage({ onLogin }: { onLogin: (me: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await authApi.login(email, password));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login-art" aria-hidden="true">
        <div className="cyc">
          <span className="cyc-shadow" />
          {/* ботинок на студийном фоне — то, ради чего сервис */}
          <svg className="cyc-boot" viewBox="0 0 200 200" aria-hidden="true">
            <path d="M62 18h46c4 0 7 3 7 7v78c0 8 5 14 13 17l30 11c12 4 20 14 20 26v8c0 4-3 7-7 7H48c-5 0-9-4-9-9v-18c0-10 3-19 9-27 6-9 8-19 8-30V25c0-4 3-7 6-7z"
              fill="#2b2f46" />
            <path d="M39 172h132" stroke="#4c3fd8" strokeWidth="6" strokeLinecap="round" />
            <path d="M115 60h-20M115 74h-20M115 88h-20" stroke="#5a5f80" strokeWidth="4" strokeLinecap="round" />
          </svg>
        </div>
        <p>Фото для карточек маркетплейсов — от съёмки на белом фоне до образов на модели.</p>
      </div>
      <form className="login-form" onSubmit={submit}>
        <a className="back-home" href="/">← На главную</a>
        <div className="logo">Dream<b>Goods</b></div>
        <h2>Вход в кабинет</h2>
        <label className="field">
          <span>Логин или почта</span>
          <input autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Пароль</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="err-text">{error}</div>}
        <button className="primary big" disabled={busy || !email || !password}>{busy ? "Вхожу…" : "Войти"}</button>
        <p className="hint">Нет доступа? Учётные записи выдаёт администратор сервиса. <a href="/pricing">Цены и оплата</a></p>
        <SiteFooter className="on-light" />
      </form>
    </div>
  );
}
