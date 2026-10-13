import { useRef, useState } from "react";
import { filesFromDrop, filesFromInput, type PickedFile } from "./files";

export interface ImportOptions {
  group_mode: "auto" | "folders";
  label_mode: "read" | "skip" | "keep";
  auto_profile: boolean;
}

interface Props {
  total: number;
  uploading: number;
  options: ImportOptions;
  onOptions: (o: ImportOptions) => void;
  onFiles: (files: PickedFile[]) => void;
  onAnalyze: () => void;
}

export function UploadStep({ total, uploading, options: o, onOptions, onFiles, onAnalyze }: Props) {
  const [over, setOver] = useState(false);
  const filesRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const sheets = Math.max(1, Math.ceil(Math.max(total - 4, 1) / 16));

  return (
    <>
      <div className={`drop ${over ? "over" : ""}`}
        onDragEnter={(e) => { e.preventDefault(); setOver(true); }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={async (e) => { e.preventDefault(); setOver(false); onFiles(await filesFromDrop(e.dataTransfer)); }}>
        <b>Перетащите сюда фото, папку или ZIP-архив</b>
        <div className="mt8">или <button onClick={() => filesRef.current?.click()}>выберите файлы</button>{" "}
          <button onClick={() => dirRef.current?.click()}>выберите папку</button></div>
        <div className="hint mt10">
          {total ? `Загружено фото: ${total}${uploading ? " · загружаю…" : ""}` : uploading ? "Загружаю…" : "Пока ничего не загружено"}
        </div>
      </div>
      <input ref={filesRef} type="file" multiple accept="image/*,.zip" hidden
        onChange={(e) => { onFiles(filesFromInput(e.target.files)); e.target.value = ""; }} />
      <input ref={dirRef} type="file" multiple hidden {...{ webkitdirectory: "" }}
        onChange={(e) => { onFiles(filesFromInput(e.target.files)); e.target.value = ""; }} />

      <div className="opts">
        <label className="form-label">Как разложить</label>
        <div className="ch">
          <label><input type="radio" checked={o.group_mode === "auto"} onChange={() => onOptions({ ...o, group_mode: "auto" })} /> Фото общей кучей — разложить по товарам автоматически</label>
          <div className="hint">порядок съёмки + ИИ смотрит, где один и тот же товар; артикул берётся с этикеток</div>
          <label><input type="radio" checked={o.group_mode === "folders"} onChange={() => onOptions({ ...o, group_mode: "folders" })} /> Уже разложены по папкам — одна папка = один артикул</label>
        </div>
        <label className="form-label">Фото этикеток и бирок</label>
        <div className="ch">
          <label><input type="radio" checked={o.label_mode === "read"} onChange={() => onOptions({ ...o, label_mode: "read" })} /> Прочитать артикул и данные, в генерацию не брать <span className="tag">рекомендуем</span></label>
          <div className="hint">этикетки сохранятся отдельно от фото товара, текст с них попадёт в профиль</div>
          <label><input type="radio" checked={o.label_mode === "skip"} onChange={() => onOptions({ ...o, label_mode: "skip" })} /> Не использовать совсем</label>
          <label><input type="radio" checked={o.label_mode === "keep"} onChange={() => onOptions({ ...o, label_mode: "keep" })} /> Оставить как обычные фото товара</label>
          <div className="hint">надписи на самом товаре (текст на банке крема, принт) — это не этикетка, их ИИ оставит в фото товара</div>
        </div>
        <label className="form-label">После раскладки</label>
        <label className="check"><input type="checkbox" checked={o.auto_profile} onChange={(e) => onOptions({ ...o, auto_profile: e.target.checked })} /> сразу составить профиль товара и промпты для новых товаров</label>
      </div>
      <div className="row mt16">
        <span className="spacer" />
        <button className="primary" disabled={!total || uploading > 0} onClick={onAnalyze}>
          {total ? `Анализировать ${total} фото (≈ ${sheets} запрос(ов) к модели)` : "Анализировать"}
        </button>
      </div>
    </>
  );
}
