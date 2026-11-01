import { useEffect, useState } from "react";
import { authApi, legalApi } from "../../api/client";
import type { LegalDocBrief, Me } from "../../api/types";
import { LegalChecks, requiredMissing } from "../../components/LegalChecks";
import { SiteFooter } from "../../layout/SiteFooter";

type Mode = "login" | "register" | "sent";
const UNVERIFIED = "почта не подтверждена";

/** Вход и регистрация. Регистрация создаёт кабинет; войти можно после подтверждения почты по ссылке из письма. */
export function LoginPage({ onLogin }: { onLogin: (me: Me) => void }) {
  const [mode, setMode] = useState<Mode>(() => (new URLSearchParams(window.location.search).has("register") ? "register" : "login"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [legal, setLegal] = useState<{ open: boolean; docs: LegalDocBrief[] } | null>(null);

  useEffect(() => {
    legalApi.list().then((d) => setLegal({ open: d.registration_open, docs: d.docs.filter((x) => x.where === "register") }))
      .catch(() => setLegal({ open: false, docs: [] }));
  }, []);

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
      <div className="login-form">
        <a className="back-home" href="/">← На главную</a>
        <div className="logo">Dream<b>Goods</b></div>
        {mode !== "sent" && (
          <div className="seg login-tabs">
            <button className={mode === "login" ? "on" : ""} onClick={() => { setMode("login"); setError(""); }}>Вход</button>
            <button className={mode === "register" ? "on" : ""} onClick={() => { setMode("register"); setError(""); }}>Регистрация</button>
          </div>
        )}
        {mode === "login" && (
          <form onSubmit={submit} className="login-fields">
            <label className="field">
              <span>Почта или логин</span>
              <input autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="field">
              <span>Пароль</span>
              <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            {error && <div className="err-text">{error}</div>}
            {error.startsWith(UNVERIFIED) && <Resend email={email} />}
            <button className="primary big" disabled={busy || !email || !password}>{busy ? "Вхожу…" : "Войти"}</button>
            <p className="hint">Нет кабинета? <button type="button" className="link" onClick={() => setMode("register")}>Зарегистрируйтесь</button>
              {" "}· <a href="/pricing">Цены и оплата</a></p>
          </form>
        )}
        {mode === "register" && legal && (legal.open
          ? <RegisterForm docs={legal.docs} onSent={(em) => { setEmail(em); setMode("sent"); }} />
          : <p className="hint">Регистрация на сайте сейчас закрыта — напишите нам, и мы заведём кабинет.</p>)}
        {mode === "sent" && (
          <div className="login-sent">
            <h2>Проверьте почту</h2>
            <p>Мы отправили письмо на <b>{email}</b>. Перейдите по ссылке из письма — почта подтвердится, и кабинет откроется.
              Ссылка действует 48 часов.</p>
            <p className="hint">Письма нет? Проверьте папку «Спам» или отправьте ещё раз.</p>
            <Resend email={email} />
            <button className="link" onClick={() => setMode("login")}>← Ко входу</button>
          </div>
        )}
        <SiteFooter className="on-light" />
      </div>
    </div>
  );
}

function RegisterForm({ docs, onSent }: { docs: LegalDocBrief[]; onSent: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const missing = requiredMissing(docs, checked);
  const okEmail = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email.trim());
  const valid = okEmail && name.trim().length >= 2 && password.length >= 6 && password === password2 && !missing.length;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError("");
    try {
      const r = await authApi.register(email.trim(), name.trim(), password, [...checked]);
      onSent(r.email);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="login-fields">
      <label className="field">
        <span>Почта</span>
        <input autoFocus type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="field">
        <span>Имя или название магазина</span>
        <input autoComplete="organization" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span>Пароль <small className="hint">— не короче 6 символов</small></span>
        <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <label className="field">
        <span>Пароль ещё раз</span>
        <input type="password" autoComplete="new-password" value={password2} onChange={(e) => setPassword2(e.target.value)} />
      </label>
      {password2 && password !== password2 && <div className="err-text">пароли не совпадают</div>}
      <LegalChecks docs={docs} checked={checked} onChange={setChecked} />
      {error && <div className="err-text">{error}</div>}
      <button className="primary big" disabled={busy || !valid}
        title={missing.length ? "Нужно согласие: " + missing.map((d) => d.title).join(", ") : ""}>
        {busy ? "Регистрирую…" : "Зарегистрироваться"}</button>
      <p className="hint">После регистрации придёт письмо со ссылкой для подтверждения почты. Новый кабинет — на тарифе
        «Старт»: оплата операций с баланса.</p>
    </form>
  );
}

/** Отправить письмо со ссылкой ещё раз (не чаще раза в минуту). */
function Resend({ email }: { email: string }) {
  const [left, setLeft] = useState(0);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!left) return;
    const t = window.setTimeout(() => setLeft((x) => x - 1), 1000);
    return () => window.clearTimeout(t);
  }, [left]);
  const send = async () => {
    try {
      await authApi.resend(email);
      setMsg("Письмо отправлено ещё раз");
      setLeft(60);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <div className="resend">
      <button type="button" disabled={!email || left > 0} onClick={send}>
        {left ? `Отправить снова через ${left} с` : "Отправить письмо ещё раз"}</button>
      {msg && <span className="hint">{msg}</span>}
    </div>
  );
}
