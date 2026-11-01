import type { PricePlan, QualityLevel } from "../api/types";

export const rubInt = (v: number) => `${Math.round(v).toLocaleString("ru-RU")} ₽`;

/** Значение тарифа в таблице сравнения. */
export function planCell(pl: PricePlan, key: keyof PricePlan, qnames: Record<QualityLevel, string>): string {
  const v = pl[key];
  if (key === "price") return pl.price ? `${rubInt(pl.price)}` : "0 ₽, оплата по факту";
  if (key === "qualities") return pl.qualities.map((q) => qnames[q] || q).join(", ");
  if (key === "storage_gb") return `${v} ГБ`;
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (v === null) return "без ограничений";
  if (v === 0) return "—";
  return String(v);
}

const lim = (n: number | null, one: string) => (n === null ? `${one}: без ограничений` : `${one}: ${n}`);

/** Главное о тарифе для карточки (4–6 строк). */
export function planHighlights(pl: PricePlan, qnames: Record<QualityLevel, string>): string[] {
  const out = [
    `качество: ${pl.qualities.map((q) => qnames[q] || q).join(", ")}`,
    `${pl.parallel} генераций одновременно`,
    `хранилище ${pl.storage_gb} ГБ`,
    lim(pl.projects, "проекты"),
  ];
  if (pl.presets !== 0) out.push(lim(pl.presets, "свои пресеты"));
  if (pl.personas !== 0) out.push(lim(pl.personas, "свои модели-люди"));
  if (pl.manual_plan) out.push("ручной план и модель на каждый блок");
  if ((pl.users ?? 2) > 1) out.push(lim(pl.users, "пользователи"));
  return out;
}
