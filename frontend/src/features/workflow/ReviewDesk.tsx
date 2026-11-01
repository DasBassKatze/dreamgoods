import { useCallback, useEffect, useMemo, useState } from "react";
import { assetUrl } from "../../api/client";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";

export function ReviewDesk() {
  const { state, api, reload } = useProject();
  const ui = useUI();
  const [filter,setFilter] = useState("review");
  const [focus,setFocus] = useState<number | null>(null);
  const [selected,setSelected] = useState<Set<number>>(new Set());
  const [comment,setComment] = useState("");
  const [reason,setReason] = useState("Изменён товар");
  const [regen,setRegen] = useState(false);
  const [busy,setBusy] = useState(false);
  const [page,setPage] = useState(0);
  const all = useMemo(() => state.products.flatMap((product) => product.frames.filter((f) => f.asset && f.generation && f.state === "done").map((frame) => ({product,frame}))),[state.products]);
  const rows = useMemo(() => all.filter(({frame:f}) => filter === "all" || (filter === "review" ? !f.qc || ["review","unchecked"].includes(f.qc.status) : f.qc?.status === filter)),[all,filter]);
  const current = rows.find((r) => r.frame.id === focus) ?? rows[0];
  useEffect(() => {setSelected(new Set());setPage(0);},[filter]);
  useEffect(() => {setComment("");},[current?.frame.id,current?.frame.generation]);
  const act = useCallback(async (verdict:"ok"|"bad", batch=false) => {
    const targets = batch ? rows.filter((r) => selected.has(r.frame.id)).slice(0,100) : current ? [current] : [];
    if (busy || !targets.length) return;
    const note = verdict === "bad" ? `${reason}${comment.trim() ? ": " + comment.trim() : ""}` : comment.trim();
    if (batch && !await ui.confirm({title:"Массовая приёмка",text:`Принять ${targets.length} выбранных кадр(ов)?`,ok:"Принять"}))return;
    if (verdict === "bad" && regen && !await ui.confirm({title:"Брак и переделка",text:"Отклонить кадр и запустить платную перегенерацию с замечанием?",ok:"Отклонить и переделать"}))return;
    setBusy(true);
    try {
      const result = await api.reviewBatch(targets.map((r) => ({frame_id:r.frame.id,generation_id:r.frame.generation!})),verdict,note,verdict === "bad" && regen);
      const errors = result.results.filter((r) => !r.ok);
      ui.toast(`Обработано: ${result.results.length-errors.length}${errors.length ? ` · ошибки: ${errors.map((r) => r.error).join("; ")}` : ""}`,6000);
      setSelected(new Set());
      if (!batch) {const i=rows.findIndex((r) => r.frame.id === current?.frame.id);setFocus(rows[i+1]?.frame.id ?? rows[i-1]?.frame.id ?? null);}
      await reload();
    } catch(e) {ui.toast((e as Error).message);} finally {setBusy(false);}
  },[api,busy,comment,current,reason,regen,reload,rows,selected,ui]);
  useEffect(() => {
    const key=(e:KeyboardEvent) => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || e.target instanceof HTMLElement && (e.target.closest("input,textarea,select,[contenteditable=true]") || document.querySelector('[role="dialog"]')))return;
      const i=rows.findIndex((r) => r.frame.id === current?.frame.id);
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {e.preventDefault();setFocus(rows[Math.max(0,Math.min(rows.length-1,i+(e.key === "ArrowRight"?1:-1)))]?.frame.id ?? null);}
      if (e.code === "KeyA") {e.preventDefault();void act("ok");}
      if (e.code === "KeyR") {e.preventDefault();void act("bad");}
    };
    window.addEventListener("keydown",key);return()=>window.removeEventListener("keydown",key);
  },[rows,current,act]);
  const pages=Math.max(1,Math.ceil(rows.length/60));
  const actualPage=Math.min(page,pages-1);
  const visible=rows.slice(actualPage*60,(actualPage+1)*60);
  const refs=current?.product.photos.filter((p)=>p.selected && p.role === "product") ?? [];
  return <section className="review-desk"><div className="row wrap"><h1>Приёмка</h1><span className="spacer" />
    <select aria-label="Статус приёмки" value={filter} onChange={(e)=>setFilter(e.target.value)}><option value="review">Требуют решения</option><option value="all">Все готовые</option><option value="pass">Прошли ИИ-проверку</option><option value="accepted">Приняты вручную</option></select>
    <button disabled={busy || !selected.size} onClick={()=>void act("ok",true)}>Принять выбранные ({selected.size})</button>
  </div><p className="hint">← → — листать · A — принять · R — отклонить. За раз можно принять до 100 кадров. Автоматическая ИИ-проверка и ручное решение сохраняются отдельно.</p>
  {!current ? <div className="panel empty">Нет кадров для выбранного фильтра.</div> : <>
    <div className="review-compare"><figure><figcaption>Референс · {current.product.sku}</figcaption>{refs[0] ? <button onClick={()=>ui.zoom(refs.map((p)=>assetUrl(p.asset)))}><img src={assetUrl(refs[0].asset,1000)} alt="Референс товара" /></button> : <p>Референс не выбран</p>}</figure>
      <figure><figcaption>Результат · кадр {current.frame.i} · версия #{current.frame.generation}</figcaption><button onClick={()=>ui.zoom([assetUrl(current.frame.asset!)])}><img src={assetUrl(current.frame.asset!,1000)} alt="Результат генерации" /></button></figure>
    </div>
    <div className="panel review-decision"><p>{current.frame.qc?.defects.join("; ") || "Замечаний ИИ нет или проверка не проводилась."}</p>
      <div className="row wrap"><select aria-label="Причина брака" value={reason} onChange={(e)=>setReason(e.target.value)}>{["Изменён товар","Неверный цвет","Потеряны детали","Анатомия","Композиция","Другое"].map((r)=><option key={r}>{r}</option>)}</select>
      <input aria-label="Комментарий к решению" value={comment} maxLength={1200} onChange={(e)=>setComment(e.target.value)} placeholder="Что нужно исправить" />
      <label><input type="checkbox" checked={regen} onChange={(e)=>setRegen(e.target.checked)} /> После брака переделать · платно</label>
      <button disabled={busy} className="primary" onClick={()=>void act("ok")}>Принять · A</button><button disabled={busy} onClick={()=>void act("bad")}>Отклонить · R</button></div>
    </div>
    <div className="row wrap"><button onClick={()=>setSelected(new Set(visible.map((r)=>r.frame.id)))}>Выбрать страницу</button><button onClick={()=>setSelected(new Set())}>Снять выбор</button><span className="spacer" /><button disabled={actualPage===0} onClick={()=>setPage(actualPage-1)}>←</button><span>{actualPage+1} / {pages}</span><button disabled={actualPage+1>=pages} onClick={()=>setPage(actualPage+1)}>→</button></div>
    <div className="review-strip">{visible.map(({product,frame})=><div key={frame.id} className={current.frame.id===frame.id?"on":""}>
      <label><input type="checkbox" checked={selected.has(frame.id)} onChange={(e)=>setSelected((prev)=>{const next=new Set(prev);if(e.target.checked)next.add(frame.id);else next.delete(frame.id);return next;})} /> {product.sku} · {frame.i}</label>
      <button onClick={()=>setFocus(frame.id)}><img src={assetUrl(frame.asset!,240)} alt={`${product.sku}, кадр ${frame.i}`} /></button></div>)}</div>
  </>}
  </section>;
}
