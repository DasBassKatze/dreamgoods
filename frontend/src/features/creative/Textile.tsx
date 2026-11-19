import { useEffect, useRef, useState, type MouseEvent } from "react";
import { transfer, type Point, type Region } from "./textileRender";

function coords(e:MouseEvent<HTMLElement>):Point {
  const r=e.currentTarget.getBoundingClientRect();
  return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];
}
const corners=(p:Point[])=>p.map(([x,y])=>`${x*100},${y*100}`).join(" ");
function picture(blob:Blob):Promise<HTMLImageElement> {
  return new Promise((resolve,reject)=>{
    const url=URL.createObjectURL(blob), img=new Image();
    img.onload=()=>resolve(img);
    img.onerror=()=>{URL.revokeObjectURL(url); reject(new Error("Фотография не читается"));};
    img.src=url;
  });
}
export function Textile(){
  const [photo,setPhoto]=useState<HTMLImageElement>(),[fabric,setFabric]=useState<HTMLImageElement>();
  const [points,setPoints]=useState<Point[]>([]),[regions,setRegions]=useState<Region[]>([]);
  const [crop,setCrop]=useState<Point[]>([]),[cut,setCut]=useState(false),[zoom,setZoom]=useState(1);
  const [repeat,setRepeat]=useState(40),[angle,setAngle]=useState(0),[bend,setBend]=useState(12);
  const [output,setOutput]=useState(""),[original,setOriginal]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  useEffect(()=>()=>{if(photo) URL.revokeObjectURL(photo.src);},[photo]);
  useEffect(()=>()=>{if(fabric) URL.revokeObjectURL(fabric.src);},[fabric]);
  const revisions=useRef({photo:0,fabric:0,render:0});
  useEffect(()=>()=>{if(output) URL.revokeObjectURL(output);},[output]);
  const invalidate=()=>{revisions.current.render++;setOutput("");setError("");setOriginal(false);};
  const upload=async(file:File|undefined,kind:"photo"|"fabric")=>{
    if(!file)return;
    const revision=++revisions.current[kind];invalidate();
    try {
      if(file.size>40*1024*1024)throw new Error("Максимальный размер файла — 40 МБ");
      const img=await picture(file);
      if(revision!==revisions.current[kind]){URL.revokeObjectURL(img.src);return;}
      if(img.naturalWidth*img.naturalHeight>16000000){URL.revokeObjectURL(img.src);throw new Error("Поддерживаются фотографии до 16 мегапикселей");}
      invalidate();
      if(kind==="photo"){setPhoto(img);setPoints([]);setRegions([]);setZoom(1);}
      else {setFabric(img);setCrop([]);}
    }catch(e){if(revision===revisions.current[kind])setError((e as Error).message);}
  };
  const render=async()=>{
    if(!photo || !fabric || crop.length!==2 || !regions.length || points.length)return;
    const revision=++revisions.current.render;setBusy(true);setError("");
    try{
      await new Promise(r=>setTimeout(r,20));
      const canvas=transfer(photo,fabric,crop,regions,repeat,angle,bend);
      const file=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error("Ошибка экспорта PNG")),"image/png"));
      if(revision===revisions.current.render)setOutput(URL.createObjectURL(file));
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  };
  return <fieldset disabled={busy}><label>Исходная фотография одежды<input type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>void upload(e.target.files?.[0],"photo")}/></label>
    <label>Образец или карта тканей<input type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>void upload(e.target.files?.[0],"fabric")}/></label>
    {fabric && <><p>На образце отметьте два противоположных угла одного повтора узора, без номера и полей.</p>
      <div className="creative-board swatch" onClick={e=>{invalidate();setCrop(crop.length===1?[crop[0],coords(e)]:[coords(e)]);}}>
      <img src={fabric.src} alt="Карта тканей"/>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">{crop.length===2 && <rect x={Math.min(crop[0][0],crop[1][0])*100} y={Math.min(crop[0][1],crop[1][1])*100} width={Math.abs(crop[0][0]-crop[1][0])*100} height={Math.abs(crop[0][1]-crop[1][1])*100}/>}
      {crop.map(([x,y],i)=><circle key={i} cx={x*100} cy={y*100} r=".7"/>)}</svg></div></>}
    {photo && <><p>Обведите одежду точками и замкните контур. Чтобы защитить руку или аксессуар, добавьте вырез внутри маски.</p>
      <label>Увеличение для разметки<select value={zoom} onChange={e=>setZoom(+e.target.value)}>{[1,2,4].map(z=><option key={z} value={z}>{z}×</option>)}</select></label>
      <div className="creative-scroll"><div className="creative-board" style={{width:zoom*100+"%"}} onClick={e=>{invalidate();setPoints([...points,coords(e)]);}}>
      <img src={photo.src} alt="Контур одежды"/><svg viewBox="0 0 100 100" preserveAspectRatio="none">{regions.map((r,i)=><polygon className={r.cut?"cut":""} key={i} points={corners(r.points)}/>)}<polyline points={corners(points)}/>{points.map(([x,y],i)=><circle key={i} cx={x*100} cy={y*100} r=".45"/>)}</svg></div></div>
      <div className="row"><label><input type="checkbox" checked={cut} onChange={e=>setCut(e.target.checked)}/> Вырез</label>
      <button disabled={points.length<3 || (cut && !regions.length)} onClick={()=>{invalidate();setRegions([...regions,{points,cut}]);setPoints([]);}}>Замкнуть контур</button>
      <button disabled={!points.length && !regions.length} onClick={()=>{invalidate();if(points.length)setPoints(points.slice(0,-1));else setRegions(regions.slice(0,-1));}}>Отменить шаг</button></div></>}
    <label>Ширина повтора, пикселей · {repeat}<input type="range" min="2" max="512" value={repeat} onChange={e=>{invalidate();setRepeat(+e.target.value);}}/></label>
    <label>Поворот · {angle}°<input type="range" min="-90" max="90" value={angle} onChange={e=>{invalidate();setAngle(+e.target.value);}}/></label>
    <label>Изгиб узора по складкам · {bend}<input type="range" min="0" max="80" value={bend} onChange={e=>{invalidate();setBend(+e.target.value);}}/></label>
    <button className="primary" disabled={!regions.length || !!points.length || crop.length!==2 || busy} onClick={render}>{busy?"Обработка…":"Применить ткань"}</button>
    {error && <p role="alert">{error}</p>}{output && <><div className="row"><label><input type="checkbox" checked={original} onChange={e=>setOriginal(e.target.checked)}/> Показать оригинал</label><a href={output} download="перенос-ткани.png">Скачать PNG</a></div><img className="creative-result" src={original?photo?.src:output} alt={original?"Оригинал":"Перенос ткани"}/></>}
  </fieldset>;
}
