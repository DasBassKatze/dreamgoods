import type { CostEstimate } from "../../api/client";
import { rub } from "../../lib/format";

export function parseBudget(values:Record<string,string>) {
  const parse=(v:string) => {
    if (!v?.trim()) return null;
    const n=Number(v.replace(",","."));
    if (!Number.isFinite(n) || n<0 || n>1e9) throw new Error("Бюджет должен быть числом от 0 до 1 000 000 000 ₽; пустое поле — без лимита.");
    return n;
  };
  return {budget_rub:parse(values.budget),retry_budget_rub:parse(values.retries)};
}

export const budgetFields=(suggested?:number, budget?:number|null,retries?:number|null) => [
  {key:"budget",label:"Общий бюджет, ₽ · пусто — без лимита",value:budget!==undefined ? budget===null?"":String(budget) : suggested ? suggested.toFixed(2) : ""},
  {key:"retries",label:"Из него на автоматические переделки, ₽ · пусто — без отдельного лимита",value:retries == null ? "" : String(retries)},
];

export function EstimateText({estimate:e}:{estimate?:CostEstimate}) {
  return <div className="budget-estimate">{e && <><p><b>Оценка: {rub(e.base_estimate)}</b> · {e.frames} кадр(ов), профилей: {e.profiles}.</p><p>Переделки при всех разрешённых попытках: ≈ {rub(e.retry_estimate)}. Консервативный ориентир с резервом: {rub(e.reserve_upper)} · {e.unit}.</p><p className="hint">{e.note}</p></>}
    <p className="hint">Резерв блокирует сумму до ответа провайдера. При достижении лимита — пауза. Уже отправленный запрос оплачивается по факту; цена выше резерва может превысить лимит, после чего новые запросы остановятся.</p></div>;
}
