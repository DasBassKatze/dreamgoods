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
