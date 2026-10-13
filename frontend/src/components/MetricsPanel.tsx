import type { Metrics } from "../api/types";
import { pct, rub } from "../lib/format";

/** Метрики качества и цены (только в админ-панели). */
export function MetricsPanel({ m }: { m: Metrics }) {
  return (
    <div className="met">
      <Row label="Прошли проверку с 1-й попытки" value={pct(m.first_pass)} />
      {m.by_model.length > 1 &&
        m.by_model.map((x) => <Row key={x.model} sub label={x.model} value={`${pct(x.first_pass)} из ${x.n}`} />)}
      <Row label="В ручной очереди" value={`${m.review} · ${pct(m.review_share)}`} />
      <Row label="Принято кадров" value={m.accepted} />
      <Row label="Цена принятого кадра" value={rub(m.cost_per_accepted)} />
      <Row label="Проверка на кадр" value={rub(m.qc_per_frame)} />
      {m.qc_passes.map((x) => <Row key={x.what} sub label={`${x.what}: ${x.calls} запр.`} value={rub(x.avg)} />)}
      <div className="met-note hint">Точность проверки (по вашей разметке, {m.labeled} кадр.)</div>
      <Row label="Брак пойман ИИ" value={pct(m.caught)} />
      <Row label="Пропущено брака" value={m.missed} bad={m.missed > 0} />
      <Row label="Хорошие кадры отбракованы"
        value={`${m.false_rej}${m.false_rej_pct != null ? " · " + pct(m.false_rej_pct) : ""}`} />
    </div>
  );
}

function Row({ label, value, sub, bad }: { label: string; value: string | number; sub?: boolean; bad?: boolean }) {
  return (
    <div className={sub ? "sub" : ""}>
      <span>{label}</span>
      {sub ? <span>{value}</span> : <b className={bad ? "bad-text" : ""}>{value}</b>}
    </div>
  );
}
