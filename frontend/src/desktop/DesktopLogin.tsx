import { useState } from "react";
import { authApi } from "../api/client";
import type { Me } from "../api/types";

export function DesktopLogin({ onLogin }: { onLogin: (me: Me) => void }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); if (busy) return;
    setBusy(true); setError("");
    try { onLogin(await authApi.login(login.trim(), password)); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось войти"); }
    finally { setBusy(false); }
  };
  return <main className="desktop-login">
    <div className="desktop-login-mark" aria-hidden="true">✦</div>
    <span className="desktop-eyebrow">ВАША СТУДИЯ ИЗОБРАЖЕНИЙ</span>
    <h1>DreamGoods</h1>
    <p className="desktop-login-caption">Войдите, чтобы продолжить работу</p>
    <form onSubmit={submit}>
      <label htmlFor="desktop-login">Логин</label>
      <input id="desktop-login" autoFocus autoComplete="username" value={login} placeholder="Ваш логин" onChange={e => setLogin(e.target.value)} required />
      <label htmlFor="desktop-password">Пароль</label>
      <input id="desktop-password" type="password" autoComplete="current-password" value={password} placeholder="Ваш пароль" onChange={e => setPassword(e.target.value)} required />
      {error && <div className="desktop-login-error" role="alert">{error}</div>}
      <button className="primary" disabled={busy || !login.trim() || !password}>{busy ? "Входим…" : "Войти в студию"}<span aria-hidden="true">→</span></button>
    </form>
    <span className="desktop-login-foot">DG Desktop · Локальное приложение</span>
  </main>;
}
