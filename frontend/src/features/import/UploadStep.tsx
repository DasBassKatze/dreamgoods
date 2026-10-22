import { useRef, useState } from "react";
import { filesFromDrop, filesFromInput, type PickedFile } from "./files";

export interface ImportOptions {
  ai_sort: boolean;        // ИИ раскладывает фото по товарам (иначе — одна папка = один товар)
  read_labels: boolean;    // ИИ читает бирки и этикетки: артикул, состав, цвет
  auto_profile: boolean;   // сразу составить профиль и промпты для новых товаров
  sort_rule: string;       // своё правило раскладки словами (необязательно) — подсказка ИИ
}

/** Режим раскладки и бирок для сервиса из галочек. */
export const importModes = (o: ImportOptions) => ({
  group_mode: o.ai_sort ? "auto" : o.read_labels ? "folders" : "none",
  label_mode: o.read_labels ? "read" : "skip",
});

interface Props {
  total: number;
  uploading: number;
  options: ImportOptions;
  onOptions: (o: ImportOptions) => void;
  onFiles: (files: PickedFile[]) => void;
  onAnalyze: () => void;
  onRestart?: () => void;
}

export function UploadStep({ total, uploading, options: o, onOptions, onFiles, onAnalyze, onRestart }: Props) {
  const [over, setOver] = useState(false);
  const filesRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const sheets = Math.max(1, Math.ceil(Math.max(total - 4, 1) / 16));

  const analysis = o.ai_sort || o.read_labels;
  return (
    <>
      <div className={`drop ${over ? "over" : ""}`}
        onDragEnter={(e) => { e.preventDefault(); setOver(true); }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={async (e) => { e.preventDefault(); setOver(false); onFiles(await filesFromDrop(e.dataTransfer)); }}>
        <b>Перетащите сюда фото или папку с фото</b>
        <div className="mt8">или <button onClick={() => filesRef.current?.click()}>выберите файлы</button>{" "}
          <button onClick={() => dirRef.current?.click()}>выберите папку</button></div>
        <div className="hint mt10">
          {total ? `Загружено фото: ${total}${uploading ? " · загружаю…" : ""}` : uploading ? "Загружаю…" : "Пока ничего не загружено"}
          {" · "}JPG, PNG, WEBP, HEIC. Архивы не принимаются — распакуйте и загрузите папку.
        </div>
      </div>
      <input ref={filesRef} type="file" multiple accept="image/*" hidden
        onChange={(e) => { onFiles(filesFromInput(e.target.files)); e.target.value = ""; }} />
      <input ref={dirRef} type="file" multiple hidden {...{ webkitdirectory: "" }}
        onChange={(e) => { onFiles(filesFromInput(e.target.files)); e.target.value = ""; }} />

      <div className="opts">
        <label className="form-label">Раскладка по товарам</label>
        <div className="ch">
          <label className="check"><input type="checkbox" checked={o.ai_sort} onChange={(e) => onOptions({ ...o, ai_sort: e.target.checked })} />
            {" "}разложить по товарам с помощью ИИ</label>
          <div className="hint">{o.ai_sort ? "ИИ смотрит порядок съёмки и сами фото, где один и тот же товар; артикул — с бирок"
            : "без ИИ: одна папка = один товар, фото без папки — один товар. Группы можно поправить на следующем шаге"}</div>
          {o.ai_sort && (
            <textarea className="short mt6" maxLength={1000} value={o.sort_rule}
              placeholder="Необязательно: своё правило раскладки. Например: «каждый товар снят на двух фото подряд, бирки нет» или «разные цвета одной модели — это разные товары»"
              onChange={(e) => onOptions({ ...o, sort_rule: e.target.value })} />
          )}
        </div>
        <label className="form-label">Бирки и этикетки</label>
        <div className="ch">
          <label className="check"><input type="checkbox" checked={o.read_labels} onChange={(e) => onOptions({ ...o, read_labels: e.target.checked })} />
            {" "}прочитать бирки: артикул, состав, цвет <span className="tag">рекомендуем</span></label>
          <div className="hint">фото бирок не идут в генерацию, текст с них попадёт в профиль товара. На следующем шаге можно
            отметить бирку вручную и описать товар словами</div>
        </div>
        <label className="form-label">После загрузки</label>
        <label className="check"><input type="checkbox" checked={o.auto_profile} onChange={(e) => onOptions({ ...o, auto_profile: e.target.checked })} />
          {" "}сразу составить профиль товара и промпты для новых товаров</label>
      </div>
      <div className="row mt16">
        {onRestart && <button onClick={onRestart} disabled={uploading > 0}>Начать заново</button>}
        <span className="spacer" />
        <button className="primary" disabled={!total || uploading > 0} onClick={onAnalyze}>
          {!analysis ? (total ? `Загрузить ${total} фото` : "Загрузить")
            : total ? `Анализировать ${total} фото (≈ ${sheets} запрос(ов) к модели)` : "Анализировать"}
        </button>
      </div>
    </>
  );
}
