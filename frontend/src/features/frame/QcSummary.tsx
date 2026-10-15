import type { Frame, QcCounts } from "../../api/types";
import { rub } from "../../lib/format";

const TITLE: Record<string, string> = {
  pass: "ИИ-проверка пройдена",
  review: "ИИ нашёл брак — нужно ваше решение",
  accepted: "✔ Принято вами",
};

export function QcSummary({ frame: f }: { frame: Frame }) {
  const q = f.qc;
  if (q && q.status === "rejected") {
    return <div className="qc review"><h4>✗ Отклонён вручную</h4></div>;
  }
  if (q && q.status !== "unchecked") {
    return (
      <div className={`qc ${q.status === "review" ? "review" : "pass"}`}>
        <h4>{TITLE[q.status] || "Проверка"}</h4>
        {q.counts && <Counts counts={q.counts} />}
        {q.defects.length > 0 && (
          <div className="def">
            <b>Причины брака:</b>
            <ul>{q.defects.map((d) => <li key={d}>{d}</li>)}</ul>
          </div>
        )}
        <div className="hint mt6">попыток: {q.attempts || 1}
          {q.cost != null && <> · затраты на кадр: {rub(q.cost)}</>}{q.model && <> · проверял: {q.model}</>}</div>
      </div>
    );
  }
  if (f.asset) {
    return (
      <div className="qc">
        <h4>Кадр не проверялся ИИ</h4>
        <div className="hint">Нажмите «Проверить ИИ» или оцените сами.</div>
      </div>
    );
  }
  return null;
}

const BODY: Record<string, string> = { heads: "голов", arms: "рук", legs: "ног", feet: "стоп" };

function Counts({ counts }: { counts: QcCounts }) {
  if (!counts.people) return null;
  const cmp = (a: number | null, b: number | null) =>
    b == null || a == null || a === b ? <>{a ?? "?"}</> : <><b className="bad-text">{a}</b> (нужно {b})</>;
  const body = (counts.body || [])
    .map((b) => Object.keys(BODY).filter((k) => b[k] != null).map((k) => `${BODY[k]} ${b[k]}`).join(", "))
    .filter(Boolean);
  return (
    <div className="hint mt4">
      Подсчёт: людей {cmp(counts.people[0], counts.people[1])}
      {(counts.entities || []).map((e) => <span key={e.name}> · {e.name} {cmp(e.got, e.expected)}</span>)}
      {body.length > 0 && <><br />Анатомия: {body.join(" | ")}</>}
    </div>
  );
}
