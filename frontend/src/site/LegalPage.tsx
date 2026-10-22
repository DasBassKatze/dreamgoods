import { useEffect, useState, type ReactElement } from "react";
import { legalApi } from "../api/client";
import type { LegalDoc } from "../api/types";
import { SiteLayout } from "./SiteLayout";

/** Текст документа сервиса (политика, соглашение, согласия). Строки «# …» — подзаголовки, «- …» — пункты. */
export function LegalPage({ kind }: { kind: string }) {
  const [doc, setDoc] = useState<LegalDoc | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    legalApi.doc(kind).then((d) => { setDoc(d); document.title = `${d.title} — DreamGoods`; }).catch((e) => setError((e as Error).message));
  }, [kind]);
  return (
    <SiteLayout page="legal">
      <article className="site-wrap legal-doc">
        {error && <p className="err-text">{error}</p>}
        {!doc && !error && <p className="hint">Загружаю…</p>}
        {doc && <>
          <h1>{doc.title}</h1>
          <p className="hint">Редакция {doc.version}{doc.updated ? ` от ${new Date(doc.updated).toLocaleDateString("ru-RU")}` : ""}</p>
          <LegalBody text={doc.body} />
        </>}
      </article>
    </SiteLayout>
  );
}

export function LegalBody({ text }: { text: string }) {
  const blocks: ReactElement[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={`u${blocks.length}`}>{list.map((x, i) => <li key={i}>{x}</li>)}</ul>);
    list = [];
  };
  text.split(/\n/).forEach((raw) => {
    const line = raw.trim();
    if (line.startsWith("- ")) { list.push(line.slice(2)); return; }
    flush();
    if (!line) return;
    if (line.startsWith("# ")) blocks.push(<h2 key={blocks.length}>{line.slice(2)}</h2>);
    else blocks.push(<p key={blocks.length}>{line}</p>);
  });
  flush();
  return <div className="legal-body">{blocks}</div>;
}
