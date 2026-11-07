import { DocumentLink } from "../desktop/DocumentLink";
import type { LegalDocBrief } from "../api/types";

/** Галочки согласий: подпись документа со ссылкой на его текст (/legal/<вид>, в новой вкладке). */
export function LegalChecks({ docs, checked, onChange }: {
  docs: LegalDocBrief[]; checked: Set<string>; onChange: (next: Set<string>) => void;
}) {
  const toggle = (k: string, on: boolean) => {
    const n = new Set(checked);
    if (on) n.add(k); else n.delete(k);
    onChange(n);
  };
  const all = docs.every((d) => checked.has(d.kind));
  return (
    <div className="legal-checks">
      {docs.length > 2 && (
        <label className="check legal-all">
          <input type="checkbox" checked={all} onChange={(e) => onChange(new Set(e.target.checked ? docs.map((d) => d.kind) : []))} />
          {" "}Принять всё
        </label>
      )}
      {docs.map((d) => {
        // подпись: «Даю [согласие на …]» — текст в скобках становится ссылкой на документ
        const m = /^(.*?)\[(.+?)\](.*)$/.exec(d.label || "") || ["", "", lower(d.title), ""];
        const [, before, linkText, after] = m;
        return (
          <label key={d.kind} className="check">
            <input type="checkbox" checked={checked.has(d.kind)} onChange={(e) => toggle(d.kind, e.target.checked)} />
            <span>
              {before}
              <DocumentLink kind={d.kind}>{linkText}</DocumentLink>
              {after}
              {d.required && <span className="req" title="обязательно">*</span>}
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** «Даю согласие на …» — название документа со строчной буквы внутри фразы. */
const lower = (t: string) => (t ? t[0].toLowerCase() + t.slice(1) : t);

export const requiredMissing = (docs: LegalDocBrief[], checked: Set<string>) =>
  docs.filter((d) => d.required && !checked.has(d.kind));
