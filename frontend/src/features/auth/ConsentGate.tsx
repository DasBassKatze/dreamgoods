import { useState } from "react";
import { authApi } from "../../api/client";
import type { Me } from "../../api/types";
import { LegalChecks, requiredMissing } from "../../components/LegalChecks";

/** Новые редакции обязательных документов: пока пользователь их не примет, кабинет не открывается. */
export function ConsentGate({ me, onDone, onLogout }: { me: Me; onDone: (me: Me) => void; onLogout: () => void }) {
  const docs = me.consents_required || [];
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const missing = requiredMissing(docs, checked);
  const save = async () => {
    setBusy(true);
    try {
      await authApi.acceptConsents([...checked]);
      onDone(await authApi.me());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="verify-page consent-gate">
      <div className="logo">Dream<b>Goods</b></div>
      <h2>Документы сервиса</h2>
      <p>Чтобы продолжить работу, ознакомьтесь с документами и подтвердите согласие. Тексты открываются по ссылкам.
        {docs.some((d) => d.version > 1) ? " Некоторые документы обновились с прошлого входа." : ""}</p>
      <LegalChecks docs={docs} checked={checked} onChange={setChecked} />
      {error && <p className="err-text">{error}</p>}
      <div className="row">
        <button onClick={onLogout}>Выйти</button>
        <span className="spacer" />
        <button className="primary" disabled={busy || missing.length > 0} onClick={save}>Принять и продолжить</button>
      </div>
    </div>
  );
}
