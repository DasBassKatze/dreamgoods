import { useEffect, useRef, useState } from "react";
import { assetUrl } from "../api/client";

export interface ZoomImage {
  asset: string;
  caption?: string;
}

/** Просмотр фото крупно: листание ← →, клик или колёсико — увеличение до 2.5× с перемещением за мышью
 *  (на телефоне — щипок пальцами средствами браузера), Esc — закрыть. Общий для всего сервиса (useUI().zoom). */
export function Lightbox({ images, start, onClose }: { images: ZoomImage[]; start: number; onClose: () => void }) {
  const [i, setI] = useState(Math.min(Math.max(start, 0), images.length - 1));
  const [scale, setScale] = useState(1);
  const [origin, setOrigin] = useState("50% 50%");
  const [loaded, setLoaded] = useState(false);
  const [hiFail, setHiFail] = useState<Record<string, boolean>>({});   // оригинал не показывается браузером (HEIC и т. п.)
  const box = useRef<HTMLDivElement>(null);
  const img = images[i];
  const many = images.length > 1;

  const go = (d: number) => {
    if (!many) return;
    setI((x) => (x + d + images.length) % images.length);
    setScale(1);
    setLoaded(false);
  };

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "+" || e.key === "=") setScale((s) => Math.min(4, s + 0.5));
      else if (e.key === "-") setScale((s) => Math.max(1, s - 0.5));
      else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [images.length, onClose]);

  // соседние фото подгружаются заранее — листание без задержки
  useEffect(() => {
    if (!many) return;
    [1, -1].forEach((d) => { const im = new Image(); im.src = assetUrl(images[(i + d + images.length) % images.length].asset, 1600); });
  }, [i, images, many]);

  const follow = (e: React.MouseEvent) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    setOrigin(`${((e.clientX - r.left) / r.width) * 100}% ${((e.clientY - r.top) / r.height) * 100}%`);
  };

  if (!img) return null;
  return (
    <div className="lightbox" role="dialog" aria-label="Просмотр фото" onClick={onClose}>
      <div className="lb-top" onClick={(e) => e.stopPropagation()}>
        <span className="lb-cap">{many ? `${i + 1} / ${images.length}` : ""}{img.caption ? `${many ? " · " : ""}${img.caption}` : ""}</span>
        <span className="spacer" />
        <button title="Уменьшить (−)" disabled={scale <= 1} onClick={() => setScale((s) => Math.max(1, s - 0.5))}>−</button>
        <span className="lb-scale">{Math.round(scale * 100)}%</span>
        <button title="Увеличить (+)" disabled={scale >= 4} onClick={() => setScale((s) => Math.min(4, s + 0.5))}>＋</button>
        <a className="btn" href={assetUrl(img.asset)} target="_blank" rel="noreferrer">Оригинал</a>
        <button title="Закрыть (Esc)" onClick={onClose}>✕</button>
      </div>
      <div ref={box} className={`lb-stage ${scale > 1 ? "zoomed" : ""}`}
        onClick={(e) => { e.stopPropagation(); follow(e); setScale((s) => (s > 1 ? 1 : 2.5)); }}
        onMouseMove={(e) => scale > 1 && follow(e)}
        onWheel={(e) => { follow(e); setScale((s) => Math.min(4, Math.max(1, s + (e.deltaY < 0 ? 0.25 : -0.25)))); }}>
        {!loaded && <span className="spinner" />}
        {/* при увеличении — оригинал (мелкий текст бирки читается), иначе — превью 1600 px */}
        <img src={scale > 1 && !hiFail[img.asset] ? assetUrl(img.asset) : assetUrl(img.asset, 1600)} alt="" draggable={false}
          onLoad={() => setLoaded(true)} onError={() => scale > 1 && setHiFail((f) => ({ ...f, [img.asset]: true }))}
          style={{ transform: `scale(${scale})`, transformOrigin: origin, opacity: loaded ? 1 : 0 }} />
      </div>
      {many && <>
        <button className="lb-nav prev" title="Предыдущее (←)" onClick={(e) => { e.stopPropagation(); go(-1); }}>‹</button>
        <button className="lb-nav next" title="Следующее (→)" onClick={(e) => { e.stopPropagation(); go(1); }}>›</button>
      </>}
    </div>
  );
}
