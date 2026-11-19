import { useEffect, useRef, useState, type PointerEvent, type RefObject } from "react";

type Point = { x: number; y: number };
export type FabricRegion = { left: number; top: number; right: number; bottom: number };

export function FabricSelection({ file, region, onChange, imageRef, disabled }: {
  file: File;
  region: FabricRegion | null;
  onChange: (region: FabricRegion | null) => void;
  imageRef: RefObject<HTMLImageElement | null>;
  disabled: boolean;
}) {
  const [url, setUrl] = useState("");
  const [draft, setDraft] = useState<FabricRegion | null>(null);
  const drag = useRef<{ pointerId: number; start: Point } | null>(null);

  useEffect(() => {
    const localUrl = URL.createObjectURL(file);
    setUrl(localUrl);
    return () => URL.revokeObjectURL(localUrl);
  }, [file]);

  function point(event: PointerEvent<HTMLDivElement>): Point {
    const rect = event.currentTarget.getBoundingClientRect();
    const clamp = (value: number) => Math.min(1, Math.max(0, value));
    return { x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) };
  }

  function bounds(start: Point, end: Point): FabricRegion {
    return { left: Math.min(start.x, end.x), right: Math.max(start.x, end.x),
      top: Math.min(start.y, end.y), bottom: Math.max(start.y, end.y) };
  }

  const visible = draft ?? region;
  return <>
    <p className="hint" id="fabric-selection-hint">Протяните рамку по нужному образцу. Если на фото только одна ткань, можно использовать снимок целиком.</p>
    <div className="fabric-selection" aria-describedby="fabric-selection-hint"
      onPointerDown={event => {
        if (disabled || event.button !== 0 || !event.isPrimary) return;
        const start = point(event);
        drag.current = { pointerId: event.pointerId, start };
        event.currentTarget.setPointerCapture(event.pointerId);
        setDraft(bounds(start, start));
      }}
      onPointerMove={event => {
        if (drag.current?.pointerId === event.pointerId) setDraft(bounds(drag.current.start, point(event)));
      }}
      onPointerUp={event => {
        if (drag.current?.pointerId !== event.pointerId) return;
        const selected = bounds(drag.current.start, point(event));
        drag.current = null;
        setDraft(null);
        const image = imageRef.current;
        if (image && (selected.right - selected.left) * image.naturalWidth >= 2 &&
            (selected.bottom - selected.top) * image.naturalHeight >= 2) onChange(selected);
      }}
      onLostPointerCapture={() => { drag.current = null; setDraft(null); }}>
      {url && <img ref={imageRef} src={url} alt="Образец ткани для выделения" draggable={false} />}
      {visible && <div className="fabric-region" aria-hidden="true" style={{
        left: `${visible.left * 100}%`, top: `${visible.top * 100}%`,
        width: `${(visible.right - visible.left) * 100}%`, height: `${(visible.bottom - visible.top) * 100}%`,
      }} />}
    </div>
    <div className="row fabric-selection-status">
      <span role="status">{region ? "Будет использован выделенный фрагмент" : "Будет использовано фото целиком"}</span>
      {region && <button type="button" onClick={() => onChange(null)}>Сбросить выделение</button>}
    </div>
  </>;
}

export async function cropFabric(file: File, region: FabricRegion | null, image: HTMLImageElement | null) {
  if (!region) return file;
  if (!image?.naturalWidth || !image.naturalHeight) throw new Error("Образец ткани ещё не загружен");
  const x = Math.floor(region.left * image.naturalWidth);
  const y = Math.floor(region.top * image.naturalHeight);
  const width = Math.ceil(region.right * image.naturalWidth) - x;
  const height = Math.ceil(region.bottom * image.naturalHeight) - y;
  if (width * height > 16_000_000) throw new Error("Размер фрагмента должен быть не больше 16 мегапикселей");
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Не удалось подготовить фрагмент ткани");
  context.drawImage(image, x, y, width, height, 0, 0, width, height);
  const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
    blob => blob ? resolve(blob) : reject(new Error("Не удалось сохранить фрагмент ткани")), "image/png",
  ));
  return new File([png], "fabric-fragment.png", { type: "image/png" });
}
