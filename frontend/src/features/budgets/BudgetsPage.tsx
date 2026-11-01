import { useCallback,useEffect,useState } from "react";
import type { BudgetState,BatchBudget } from "../../api/client";
import { useProject } from "../../ProjectContext";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { budgetFields,parseBudget } from "./BudgetForm";

export function BudgetsPage() {
  const {api,reload}=useProject();const ui=useUI();
  const [data,setData]=useState<BudgetState|null>(null);const [busy,setBusy]=useState(false);
  const load=useCallback(async()=>setData(await api.budgets()),[api]);
  useEffect(()=>{let alive=true;const refresh=async()=>{if(document.hidden)return;try{const r=await api.budgets();if(alive)setData(r);}catch(e){if(alive)ui.toast((e as Error).message);}};void refresh();const t=window.setInterval(refresh,5000);return()=>{alive=false;window.clearInterval(t);};},[api,ui]);
  const act=async(fn:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);try{await fn();await load();await reload();}catch(e){ui.toast((e as Error).message,6000);}finally{setBusy(false);}};
  const resume=(b:BatchBudget)=>act(async()=>{
    const limits=await ui.ask({title:`Продолжить партию #${b.id}`,text:<p>Потрачено {rub(b.spent)}, зарезервировано {rub(b.reserved)}. Лимиты задаются для всей партии, включая уже потраченное. Продолжение отправит новые платные запросы.</p>,fields:budgetFields(undefined,b.budget,b.retry_budget),ok:"Продолжить"});
    if(limits)await api.resumeBudget(b.id,parseBudget(limits));
  });
  const reconcile=(id:string,action:"refresh"|"release"|"settle")=>act(async()=>{
    if(action==="refresh"){await api.reconcile(id,action);return;}
    const value=await ui.ask({title:action==="release"?"Снять резерв после сверки":"Учесть фактический расход",text:<p>Сначала проверьте операцию в кабинете Polza. Снятие резерва не отменяет задачу провайдера. Запись сверки сохранится в журнале операции.</p>,fields:[{key:"note",label:"Результат сверки",value:""},...(action==="settle"?[{key:"cost",label:"Себестоимость провайдера, ₽",value:""}]:[])],ok:"Сохранить сверку"});
    if(!value)return;const cost=action==="settle"?Number(value.cost.replace(",",".")):0;
    if(!Number.isFinite(cost)||cost<0)throw new Error("Укажите корректную себестоимость");
    await api.reconcile(id,action,value.note,cost);
  });
  return <section className="budget-page"><div className="row wrap"><h1>Бюджеты и расходы</h1><span className="spacer"/><button disabled={busy} onClick={()=>act(load)}>Обновить</button></div>
    {!data?<p>Загрузка…</p>:<>
      <div className="budget-balance"><div>Баланс<b>{rub(data.balance)}</b></div><div>В резерве<b>{rub(data.reserved)}</b></div><div>Доступно<b>{rub(data.available)}</b></div></div>
      <p className="hint">Баланс и доступная сумма относятся ко всему кабинету, партии ниже — к текущему проекту. Цена провайдера может оказаться выше оценки: уже отправленные запросы оплачиваются по факту.</p>
      {!!data.paused_jobs&&<button disabled={busy} onClick={()=>act(async()=>{if(await ui.confirm({title:"Продолжить задания",text:`Продолжить ${data.paused_jobs} приостановленных заданий без партии? Новые запросы платные.`,ok:"Продолжить"}))await api.resumeUnbatched();})}>Продолжить задания без партии ({data.paused_jobs})</button>}
      {!data.batches.length&&<p className="panel empty">Партий пока нет. Бюджет задаётся в диалоге запуска генерации.</p>}
      {data.batches.map((b)=><article className="panel budget-card" key={b.id}><div className="row wrap"><h2>#{b.id} · {b.title}</h2><span className="tag">{b.state==="paused"?"Пауза":b.state==="done"?"Завершена":"В работе"}</span><span className="spacer"/><button disabled={busy} onClick={()=>resume(b)}>Лимиты / продолжить</button></div>
        <p>{b.unit} · потрачено <b>{rub(b.spent)}</b> из {b.budget==null?"без лимита":rub(b.budget)} · резерв {rub(b.reserved)} · переделки {rub(b.retries)} из {b.retry_budget==null?"без отдельного лимита":rub(b.retry_budget)}</p>
        <p className="hint">В очереди: {b.queued} · выполняется: {b.running} · приостановлено: {b.paused}</p>
        {b.pause_reason&&<p className="bad-text">{b.pause_reason}</p>}
        {!!b.products.length&&<div className="budget-table"><table><thead><tr><th>Артикул</th><th>Расход</th><th>Резерв</th><th>Переделки</th><th>Принято кадров</th><th>Цена принятого</th></tr></thead><tbody>{b.products.map((p)=><tr key={p.product_id??0}><td>{p.sku}</td><td>{rub(p.spent)}</td><td>{rub(p.reserved)}</td><td>{rub(p.retries)}</td><td>{p.accepted}</td><td>{p.cost_per_accepted==null?"—":rub(p.cost_per_accepted)}</td></tr>)}</tbody></table></div>}
      </article>)}
      {!!data.operations.length&&<div className="panel budget-card"><h2>Незавершённые резервы</h2><p>При обрыве после отправки резерв остаётся до проверки фактического расхода.</p>{data.operations.map((o)=><div className="budget-operation" key={o.id}><b>{o.kind} · {rub(o.reserved)}</b><span> {o.model} · {o.status==="uncertain"?"нужна сверка":o.status==="submitted"?"запрос отправлен":"подготовка"}</span>
        {data.admin&&<><p className="hint">Операция {o.id} · задача {o.external_id||"номер не получен"}</p><div className="row wrap"><button disabled={busy||!o.external_id} onClick={()=>reconcile(o.id,"refresh")}>Проверить Polza</button><button disabled={busy} onClick={()=>reconcile(o.id,"settle")}>Учесть расход…</button><button disabled={busy} onClick={()=>reconcile(o.id,"release")}>Снять резерв после сверки…</button></div></>}
      </div>)}</div>}
    </>}
  </section>;
}
