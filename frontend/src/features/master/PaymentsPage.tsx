import { useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";

type Hold = {id:string; client_id:number; task:string; reserved:number; status:string; created:string};
export function PaymentsPage() {
  const [items, setItems] = useState<Hold[]>([]), [error, setError] = useState("");
  const ui = useUI();
  const load = () => adminApi.pendingPayments().then((d) => setItems(d.items)).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);
  const resolve = async (item: Hold) => {
    const v = await ui.ask({ title:"Сверка с провайдером", ok:"Зафиксировать", fields:[
      {key:"cost", label:"Фактическая себестоимость по журналу провайдера, ₽ (0 — не списано)", value:"0"},
      {key:"note", label:"Основание сверки / номер обращения", value:""},
    ] });
    if (!v) return;
    const cost = Number(v.cost.replace(",", "."));
    if (!Number.isFinite(cost) || cost < 0 || v.note.trim().length < 5) { setError("Укажите сумму и основание сверки"); return; }
    try { await adminApi.resolvePayment(item.id, cost, v.note.trim()); await load(); } catch(e) { setError((e as Error).message); }
  };
  return <section className="page"><h1>Сверка платежей</h1><p>Резервы при неопределённом ответе сохраняются, чтобы повторный запуск не привёл к перерасходу.
    Если известна задача Polza — используйте дозагрузку. Остальные сверяйте с журналом провайдера.</p>
    <div className="row wrap"><button onClick={async () => {
      const v = await ui.ask({ title:"Резерв на запрос", fields:[{key:"image",label:"Минимальный резерв генерации, себестоимость ₽",value:"50"},{key:"chat",label:"Минимальный резерв запроса ИИ, себестоимость ₽",value:"5"}] });
      if (v) { try { await adminApi.setReservePrices(Number(v.image), Number(v.chat)); ui.toast("Резервы сохранены"); } catch(e) { setError((e as Error).message); } }
    }}>Настроить резервы</button><button onClick={async () => {
      const v = await ui.ask({ title:"Потоки клиента", fields:[{key:"id",label:"ID клиента"},{key:"n",label:"Лимит одновременно запущенных заданий (1–12)",value:"2"}] });
      if(v) { try { await adminApi.setClientParallel(Number(v.id), Number(v.n)); ui.toast("Лимит сохранён"); } catch(e) { setError((e as Error).message); } }
    }}>Лимит клиента</button></div>
    <button onClick={load}>Обновить</button><button onClick={async () => { await adminApi.resume(); await load(); }}>Дозагрузить результаты</button>
    {error && <p role="alert">{error}</p>}
    {!items.length ? <p>Ожидающих сверки операций нет.</p> : <table><thead><tr><th>Клиент</th><th>Резерв</th><th>Статус</th><th>Задача</th><th /></tr></thead><tbody>{items.map((i) => <tr key={i.id}>
      <td>{i.client_id}</td><td>{rub(i.reserved)}</td><td>{i.status}</td><td>{i.task || "неизвестна"}</td><td><button disabled={i.status !== "uncertain" || (!!i.task && Date.now()-new Date(i.created).getTime()<86400000)} onClick={() => resolve(i)}>Сверить</button></td>
    </tr>)}</tbody></table>}
  </section>;
}
