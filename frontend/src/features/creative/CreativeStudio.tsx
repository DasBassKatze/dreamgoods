import { useState } from "react";
import { useProject } from "../../ProjectContext";
import { assetUrl } from "../../api/client";
import type { BlockKey, Product } from "../../api/types";
import { useActions } from "../../hooks/useActions";
import { usePersistentState } from "../../hooks/usePersistentState";
import { ManualReference } from "../presets/ManualReference";
import { Textile } from "./Textile";
import "./creative.css";

const scenes: [string, BlockKey, string, string][] = [
  ["Силуэт", "full", "Спокойная фронтальная поза в светлом зале. Руки свободны, вещь видна целиком.", "Сдержанный образ и светлый зал подчёркивают силуэт. Проверить длину и пропорции."],
  ["Движение", "full", "Лёгкий шаг по каменной лестнице, вид в три четверти. Боковой дневной свет.", "Шаг раскрывает движение ткани. Проверить складки и естественность опоры."],
  ["Посадка", "worn", "Профиль у высокого окна, мягкий рассеянный свет, нейтральная базовая стилизация.", "Боковой ракурс показывает посадку. Проверить линию швов и контур изделия."],
  ["Конструкция", "full", "Вид со спины в светлой аркаде. Волосы и аксессуары не перекрывают вещь.", "Разворот раскрывает конструкцию со спины. Проверить отделку и видимые застёжки."],
  ["Фактура", "detail", "Макро ткани и характерной отделки, рассеянный боковой свет, нейтральный фон.", "Крупный план выделяет переплетение и отделку. Сверить фактуру и реальный оттенок."],
];
const fidelity = "По исходным фотографиям сохрани цвет, крой, длину, швы, отделку и фактуру. Естественные анатомия, освещение, масштаб и тени. Не закрывай изделие и не дорисовывай детали.";

function Series({ product, userId, openFrame }: { product: Product; userId: number; openFrame: (p: number, f: number) => void }) {
  const { api, state, reload, run } = useProject();
  const { generate } = useActions();
  const key = `creative-v1:${userId}:${state.project.id}:${product.id}`;
  const [draft, setDraft] = usePersistentState(key, {
    brief: "Светлая классика, естественная кожа и нейтральный свет. Без спортивных элементов, каминов и состаренных стен.",
    shots: scenes.map(([title, block, prompt, note]) => ({title, block, prompt, note, count:1, model:"", reference_id:0, reference_description:""})),
    preset: 0, signature: "",
  });
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const patch = (i: number, fields: Partial<typeof draft.shots[number]>) => setDraft(d => ({...d, shots:d.shots.map((s,n) => i === n ? {...s,...fields} : s)}));
  const manual = draft.shots.map(({note: _note, ...s}) => ({...s,prompt:[s.prompt, draft.brief, fidelity].join("\n")}));
  const signature = JSON.stringify(manual);
  const saved = draft.signature === signature && !!draft.preset && state.presets.some(p => p.id === draft.preset);
  const assigned = saved && product.preset_id === draft.preset;
  const seriesFrames = product.frames.filter(f => draft.shots.some(shot => shot.title === f.block));
  const approved = seriesFrames.filter(f => f.asset && f.state === "done" && f.qc?.status === "accepted");
  const complete = assigned && approved.length === 5 && new Set(approved.map(f => f.block)).size === 5;
  const refs = manual.map(s=>s.reference_id).filter(Boolean);
  const duplicate = refs.length !== new Set(refs).size;
  const prepare = () => run(async () => {
    setBusy(true);
    try {
      let id = draft.preset;
      if (!saved) {
        const result = await api.savePreset(null, {name:(product.sku + " · творческая серия").slice(0,100), description:draft.brief,
          quality:"premium", strictness:"strict", market:{key:"none",cover:false,aspect:"3:4"}, plan_mode:"manual", manual,
          plan:{studio:0,detail:1,worn:1,full:3,lifestyle:0},custom:{}, block_models:{}});
        if (!("id" in result)) throw new Error("Сервер не вернул номер шаблона");
        id = result.id;
        setDraft(d=>({...d,preset:id,signature}));
      }
      await api.applyPreset(id,{product_ids:[product.id],rebuild:false});
      await reload();
    } finally { setBusy(false); }
  });
  const notes = () => {
    const body = product.sku+"\n\n"+draft.shots.map((s,i)=>`${i+1}. ${s.title}\n${s.note}`).join("\n\n");
    const url=URL.createObjectURL(new Blob([body],{type:"text/plain;charset=utf-8"}));
    const a=document.createElement("a"); a.href=url; a.download=product.sku+" — пояснения.txt"; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <><div className="creative-refs">{product.photos.map(p=><img key={p.asset} src={assetUrl(p.asset,200)} alt="Исходное фото товара"/>)}</div>
    <fieldset disabled={busy || uploading}><label>Стиль бренда и требования<textarea maxLength={650} value={draft.brief} onChange={e=>setDraft({...draft,brief:e.target.value})}/></label></fieldset>
    {draft.shots.map((s,i)=><details key={i} className="creative-shot"><summary>{i+1}. {s.title}</summary>
      <fieldset disabled={busy || uploading}><label>Сюжет, модель, место и свет<textarea maxLength={1000} value={s.prompt} onChange={e=>patch(i,{prompt:e.target.value})}/></label>
      <label>Пояснение к кадру · уточните после просмотра<textarea value={s.note} onChange={e=>patch(i,{note:e.target.value})}/></label></fieldset>
      <ManualReference item={s} locked={busy || uploading} onBusy={setUploading} onChange={fields=>patch(i,fields)}/>
    </details>)}
    {duplicate && <p role="alert">Для разных сюжетов выберите разные референсы.</p>}
    <p>План назначается только товару {product.sku}. При запуске его съёмка будет приведена к пяти кадрам. Уровень «Премиум» допускает платные переделки после проверки.</p>
    <div className="row"><button disabled={assigned || busy || uploading || duplicate || !product.photos.length || manual.some((_,i)=>!draft.shots[i].prompt.trim())} onClick={prepare}>Назначить план товару</button>
    <button className="primary" disabled={!assigned || busy || uploading} onClick={async()=>{setBusy(true);try{await generate([product.id]);}finally{setBusy(false);}}}>Запустить серию · платно</button>
    <button onClick={notes}>Скачать пояснения</button></div>
    {assigned && <div className="creative-refs">{seriesFrames.filter(f=>f.asset).map(f=><button key={f.id} onClick={()=>openFrame(product.id,f.id)}><img src={assetUrl(f.asset!,240)} alt={f.block}/>{f.block} · {f.qc?.status==="accepted"?"принят":"проверить"}</button>)}</div>}
    {assigned && <p>Принято вручную: {approved.length} из 5. Сверьте исходный цвет, крой, детали и естественность позы. {complete && <a download href={api.exportUrl("manual",{products:[product.id]})}>Скачать принятую серию ZIP</a>}</p>}
  </>;
}

export function CreativeStudio({userId, openFrame}: {userId:number;openFrame:(p:number,f:number)=>void}) {
  const {state}=useProject();
  const [mode,setMode]=useState("series");
  const [id,setId]=useState(state.products[0]?.id ?? 0);
  const product=state.products.find(p=>p.id===id);
  return <section className="creative"><h1>Творческая студия</h1><div className="row">{[["series","Серия из пяти кадров"],["fabric","Перенос ткани"]].map(([m,label])=><button key={m} aria-pressed={mode===m} onClick={()=>setMode(m)}>{label}</button>)}</div>
    <div hidden={mode!=="series"}><label>Товар<select value={product?.id ?? 0} onChange={e=>setId(+e.target.value)}><option value={0}>Выберите товар</option>{state.products.map(p=><option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}</select></label>
    {product ? <Series key={product.id} product={product} userId={userId} openFrame={openFrame}/> : <a href="#/import">Загрузить фотографии товара</a>}</div>
    <div hidden={mode!=="fabric"}><Textile/></div></section>;
}
