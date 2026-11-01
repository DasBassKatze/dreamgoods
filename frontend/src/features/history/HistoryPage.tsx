import { useCallback, useEffect, useState } from "react";
import type { Dialogs } from "../../App";
import { assetUrl } from "../../api/client";
import type { HistoryItem } from "../../api/types";
import { pad, rub } from "../../lib/format";
import { useProject } from "../../ProjectContext";

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }) : "—");
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "");

/** Вкладка «История»: все съёмки и правки кадров проекта, новые сверху. */
export function HistoryPage({ dialogs, onBalance }: { dialogs: Dialogs; onBalance: () => void }) {
  const { state, api } = useProject();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [more, setMore] = useState(false);
  const [err, setErr] = useState("");
  const done = state.totals.done;

  const load = useCallback(async () => {
    try {
      const r = await api.runs();
      setItems(r.items);
      setMore(r.items.length >= 120);
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [api]);
  useEffect(() => { load(); }, [load, done]);

  const loadMore = async () => {
    if (!items?.length) return;
    const r = await api.runs(items[items.length - 1].id);
    setItems([...items, ...r.items]);
    setMore(r.items.length >= 120);
  };

  const groups: [string, HistoryItem[]][] = [];
  for (const it of items || []) {
    const d = day(it.created);
    const last = groups[groups.length - 1];
    if (last && last[0] === d) last[1].push(it);
    else groups.push([d, [it]]);
  }

  return (
    <div className="page history">
      <div className="page-head">
        <h1>История</h1>
        <span className="hint">съёмки и правки кадров · {state.project.name}</span>
        <span className="spacer" />
        <button onClick={onBalance}>{state.admin ? "Финансы" : "Списания и баланс"}</button>
      </div>
      {err && <div className="err-text">{err}</div>}
      {items == null ? <div className="empty">Загрузка…</div> : !items.length ? (
        <div className="empty">Генераций в этом проекте пока не было.</div>
      ) : (
        <div className="hist">
          {groups.map(([d, list]) => (
            <section key={d}>
              <h3 className="hist-day">{d}</h3>
              <div className="hist-list">
                {list.map((it) => (
                  <button key={it.id} className={`hist-row st-${it.status}`} onClick={() => dialogs.openFrame(it.product_id, it.frame_id)}>
                    <span className="hist-thumb">{it.asset ? <img loading="lazy" src={assetUrl(it.asset, 120)} alt="" /> : <i>{pad(it.position)}</i>}</span>
                    <span className="hist-main">
                      <b>{it.sku} · кадр {pad(it.position)}</b>
                      <small>{it.edit ? `Правка: ${it.edit}` : `Съёмка${it.attempt > 1 ? ` · попытка ${it.attempt}` : ""}`} · {it.title}</small>
                      {it.error && <small className="err-text">{it.error}</small>}
                    </span>
                    <span className="hist-tags">
                      {it.status === "pending" && <em className="tag">ждёт ответа</em>}
                      {it.status === "error" && <em className="tag bad">ошибка</em>}
                      {it.qc === "pass" && <em className="tag good">ИИ ✓</em>}
                      {it.qc === "fail" && <em className="tag warn">брак</em>}
                      {it.current && <em className="tag cur">текущая</em>}
                    </span>
                    {state.admin && <span className="hist-cost"><small>{it.model}</small>{rub(it.cost)}</span>}
                    <span className="hist-time">{time(it.created)}</span>
                  </button>
                ))}
              </div>
            </section>
          ))}
          {more && <div className="row center"><button onClick={loadMore}>Показать ещё</button></div>}
        </div>
      )}
    </div>
  );
}
