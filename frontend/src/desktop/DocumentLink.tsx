import { useState, type ReactNode } from "react";
import { isDesktop } from "./runtime";
import { legalApi } from "../api/client";
import type { LegalDoc } from "../api/types";
import { Modal } from "../components/Modal";
import { LegalBody } from "../site/LegalPage";

export function DocumentLink({ kind, children }: { kind: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [doc, setDoc] = useState<LegalDoc | null>(null);
  const [error, setError] = useState("");
  if (!isDesktop) return <a href={`/legal/${kind}`} target="_blank" rel="noreferrer">{children}</a>;
  return <><button type="button" className="link" onClick={e => {
    e.preventDefault(); e.stopPropagation(); setOpen(true); setError("");
    void legalApi.doc(kind).then(setDoc).catch(e => setError(e.message));
  }}>{children}</button>{open && <Modal title={doc?.title || "Документ"} width={760} onClose={() => setOpen(false)}>
    <div style={{ padding: 24 }}>{error ? <p role="alert">{error}</p> : doc ? <LegalBody text={doc.body} /> : "Загрузка…"}</div>
  </Modal>}</>;
}
