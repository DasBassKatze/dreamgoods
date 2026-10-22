import { useEffect, useState } from "react";
import { authApi } from "../../api/client";

/** Ссылка из письма: /verify?token=… — подтверждаем почту и открываем студию. */
export function VerifyPage() {
  const [state, setState] = useState<"busy" | "ok" | "error">("busy");
  const [error, setError] = useState("");
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token") || "";
    authApi.verify(token)
      .then(() => { setState("ok"); window.setTimeout(() => window.location.replace("/studio"), 1200); })
      .catch((e) => { setError((e as Error).message); setState("error"); });
  }, []);
  return (
    <div className="verify-page">
      <div className="logo">Dream<b>Goods</b></div>
      {state === "busy" && <p>Подтверждаю почту…</p>}
      {state === "ok" && <><h2>Почта подтверждена</h2><p>Открываю кабинет…</p></>}
      {state === "error" && <>
        <h2>Не получилось подтвердить почту</h2>
        <p className="err-text">{error}</p>
        <a className="site-btn primary" href="/studio">Ко входу</a>
      </>}
    </div>
  );
}
