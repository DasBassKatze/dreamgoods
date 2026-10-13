import type { Frame, QcStatus } from "../api/types";

export const rub = (v: number | null | undefined) =>
  v == null ? "—" : (Math.round(v * 100) / 100).toLocaleString("ru-RU") + " ₽";

export const pct = (v: number | null | undefined) => (v == null ? "—" : `${v}%`);

export const pad = (i: number) => String(i).padStart(2, "0");

export const STATE_LABEL: Record<string, string> = {
  queued: "в очереди",
  running: "генерация",
  checking: "проверка",
  error: "ошибка",
};

export const QC_LABEL: Record<QcStatus, string> = {
  pass: "ИИ ✓",
  review: "брак?",
  accepted: "принято",
  rejected: "отклонён",
  unchecked: "",
};

const ACTIVE = new Set(["queued", "running", "checking", "error"]);

export const isActive = (f: Frame) => ACTIVE.has(f.state);
export const isBusy = (f: Frame) => f.state === "queued" || f.state === "running" || f.state === "checking";

/** Итоговый статус проверки кадра (если кадр сейчас не в работе). */
export const qcStatus = (f: Frame): QcStatus | "" => (f.qc && !isActive(f) ? f.qc.status : "");

/** Подпись на плашке кадра без повторов: «генерация», «попытка 2/3», «проверка 1/3»… */
export function badgeText(f: Frame): string {
  if (isActive(f)) {
    const label = STATE_LABEL[f.state] || "";
    const note = f.note || "";
    if (!note || note === label) return label;
    if (note.startsWith(label.split(" ")[0]) || (f.state === "checking" && note.startsWith("провер"))) return note;
    return `${label} · ${note}`;
  }
  const q = qcStatus(f);
  return q ? QC_LABEL[q] : "";
}

export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}
