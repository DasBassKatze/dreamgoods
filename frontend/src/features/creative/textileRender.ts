export type Point = [number, number];
export type Region = {points: Point[]; cut: boolean};
export function surface(width: number, height: number) {
  const canvas=document.createElement("canvas");
  canvas.width=width; canvas.height=height;
  const ctx=canvas.getContext("2d",{willReadFrequently:true});
  if (!ctx) throw new Error("Редактор изображений недоступен");
  return ctx;
}

export function transfer(photo: HTMLImageElement, fabric: HTMLImageElement, crop: Point[], regions: Region[], repeat: number, angle: number, bend: number) {
  const w=photo.naturalWidth, h=photo.naturalHeight;
  const result=surface(w,h), mask=surface(w,h);
  result.drawImage(photo,0,0);
  for (const region of regions) {
    mask.globalCompositeOperation=region.cut ? "destination-out" : "source-over";
    mask.beginPath();
    region.points.forEach(([x,y],i)=>i ? mask.lineTo(x*w,y*h) : mask.moveTo(x*w,y*h));
    mask.closePath(); mask.fill();
  }
  const coverage=mask.getImageData(0,0,w,h).data;
  const pixels=result.getImageData(0,0,w,h), source=pixels.data;
  const light=(i:number)=>(.2126*source[i]+.7152*source[i+1]+.0722*source[i+2]);
  let total=0, weight=0;
  for(let i=0;i<source.length;i+=4) {total+=light(i)*coverage[i+3]; weight+=coverage[i+3];}
  if (!weight) throw new Error("Маска пуста");
  const base=total/weight;
  const [a,b]=crop, fw=fabric.naturalWidth, fh=fabric.naturalHeight;
  const sx=Math.round(Math.min(a[0],b[0])*fw),sy=Math.round(Math.min(a[1],b[1])*fh);
  const sw=Math.round(Math.max(a[0],b[0])*fw)-sx, sh=Math.round(Math.max(a[1],b[1])*fh)-sy;
  if(sw<2 || sh<2) throw new Error("Выберите участок ткани шире двух пикселей");
  const tw=Math.max(2,Math.round(repeat)),th=Math.max(2,Math.round(tw*sh/sw));
  if (tw*th>4000000 || th>8192) throw new Error("Выберите более компактный раппорт");
  const tile=surface(tw,th);
  tile.imageSmoothingQuality="high"; tile.drawImage(fabric,sx,sy,sw,sh,0,0,tw,th);
  const tex=tile.getImageData(0,0,tw,th).data;
  const cos=Math.cos(angle*Math.PI/180),sin=Math.sin(angle*Math.PI/180);
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    const i=(y*w+x)*4, alpha=coverage[i+3]/255;
    if(!alpha) continue;
    const lum=light(i), shade=Math.min(2.6,(lum+16)/(base+16));
    const u=x*cos+y*sin+bend*(shade-1), v=y*cos-x*sin;
    const ux=Math.floor(u), vy=Math.floor(v), fx=u-ux, fy=v-vy;
    const tx=((ux%tw)+tw)%tw, ty=((vy%th)+th)%th;
    const p=(ty*tw+tx)*4, q=(ty*tw+(tx+1)%tw)*4;
    const r=(((ty+1)%th)*tw+tx)*4, s=(((ty+1)%th)*tw+(tx+1)%tw)*4;
    for(let k=0;k<3;k++){
      const value=(tex[p+k]*(1-fx)+tex[q+k]*fx)*(1-fy)+(tex[r+k]*(1-fx)+tex[s+k]*fx)*fy;
      source[i+k]=source[i+k]*(1-alpha)+Math.min(255,value*shade)*alpha;
    }
  }
  result.putImageData(pixels,0,0);
  return result.canvas;
}
