import { useRef, useState } from "react";
import { assetUrl } from "../../api/client";

export function CompareImages({ left, right, leftLabel = "Референс", rightLabel = "Результат" }: {
  left?: string | null; right?: string | null; leftLabel?: string; rightLabel?: string;
}) {
  const [zoom, setZoom] = useState(1);
  const panes = useRef<(HTMLDivElement | null)[]>([]);
  return <section className="compare">
    <label>Масштаб {zoom.toFixed(1)}× <input aria-label="Масштаб сравнения" type="range" min={1} max={4} step={0.25} value={zoom} onChange={(e) => setZoom(+e.target.value)} /></label>
    <div className="compare-grid">{[[left, leftLabel], [right, rightLabel]].map(([src, label], i) => <div key={i}>
      <b>{label}</b><div className="compare-pane" ref={(node) => { panes.current[i] = node; }}
        onScroll={(e) => { const other = panes.current[1-i], own = e.currentTarget; if (other) { other.scrollLeft = own.scrollLeft; other.scrollTop = own.scrollTop; } }}>
        {src ? <img src={assetUrl(src)} alt={label || "Сравнение"} style={{ width: `${zoom * 100}%`, maxWidth: "none" }} /> : <p>Нет изображения</p>}
      </div></div>)}</div>
  </section>;
}
