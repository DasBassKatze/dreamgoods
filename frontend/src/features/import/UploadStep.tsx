import { useRef, useState } from "react";
import type { ImportRules } from "../../api/types";
import { filesFromDrop, filesFromInput, type PickedFile } from "./files";

export const DEFAULT_RULES: ImportRules = {
  order: "auto", photos_per_product: 0, labels_per_product: -1, article_example: "", colors_separate: true,
  sizes_together: true, ignore: ["price", "barcode", "size"], rule: "",
};

const IGNORE: [ImportRules["ignore"][number], string][] = [
  ["price", "цену"], ["barcode", "цифры штрихкода"], ["size", "размер"],
];

export interface ImportOptions {
  ai_sort: boolean;        // ИИ раскладывает фото по товарам (иначе — одна папка = один товар)
  read_labels: boolean;    // ИИ читает бирки и этикетки: артикул, состав, цвет
  auto_profile: boolean;   // сразу составить профиль и промпты для новых товаров
  rules: ImportRules;      // номенклатура: как снимали и как устроены бирки — подсказка ИИ и проверки после раскладки
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
          {!o.ai_sort && <div className="hint">без ИИ: одна папка — один товар, фото без папки — один товар</div>}
        </div>
        <label className="form-label">Бирки и этикетки</label>
        <div className="ch">
          <label className="check"><input type="checkbox" checked={o.read_labels} onChange={(e) => onOptions({ ...o, read_labels: e.target.checked })} />
            {" "}прочитать бирки: артикул, состав, цвет <span className="tag">рекомендуем</span></label>
          <div className="hint">текст бирок — в профиль товара; отдельные фото бирок в генерацию не идут</div>
        </div>
        {analysis && <Nomenclature rules={o.rules} aiSort={o.ai_sort} onChange={(rules) => onOptions({ ...o, rules })} />}
        <label className="form-label">После загрузки</label>
        <label className="check"><input type="checkbox" checked={o.auto_profile} onChange={(e) => onOptions({ ...o, auto_profile: e.target.checked })} />
          {" "}сразу составить профиль товара и промпты для новых товаров</label>
      </div>
      <div className="row mt16 import-actions">
        {onRestart && <button onClick={onRestart} disabled={uploading > 0}>Начать заново</button>}
        <span className="spacer" />
        <button className="primary" disabled={!total || uploading > 0} onClick={onAnalyze}>
          {!analysis ? (total ? `Загрузить ${total} фото` : "Загрузить")
            : total ? `Анализировать ${total} фото` : "Анализировать"}
        </button>
      </div>
    </>
  );
}

/** Номенклатура загрузки: базовые правила раскладки. Запоминаются в проекте и подставляются в следующую загрузку. */
function Nomenclature({ rules: r, aiSort, onChange }: { rules: ImportRules; aiSort: boolean; onChange: (r: ImportRules) => void }) {
  const set = <K extends keyof ImportRules>(k: K, v: ImportRules[K]) => onChange({ ...r, [k]: v });
  const changed = JSON.stringify(r) !== JSON.stringify(DEFAULT_RULES);
  return (
    <>
      <label className="form-label">Номенклатура</label>
      <details className="nomen" open={changed || undefined}>
        <summary>Как вы снимаете и как устроены бирки <span className="hint">— необязательно, но раскладка точнее
          {changed ? " · заданы свои правила" : ""}</span></summary>
        <div className="nomen-grid">
          {aiSort && <>
            <span>Порядок съёмки</span>
            <select value={r.order} onChange={(e) => set("order", e.target.value as ImportRules["order"])}>
              <option value="auto">определит ИИ</option>
              <option value="label_after">сначала товар, потом его бирка</option>
              <option value="label_before">сначала бирка, потом товар</option>
              <option value="no_label">бирки не снимаю</option>
            </select>
            <span>Фото на один товар</span>
            <div className="row nowrap"><input type="number" min={0} max={50} style={{ width: 90 }} placeholder="не знаю"
              value={r.photos_per_product || ""} onChange={(e) => set("photos_per_product", Math.max(0, +e.target.value || 0))} />
              <span className="hint">примерно — большие группы ИИ отметит для проверки</span></div>
            <span>Фото бирок на товар</span>
            <select value={r.labels_per_product} onChange={(e) => set("labels_per_product", +e.target.value)}>
              <option value={-1}>не знаю</option><option value={0}>нет</option>
              <option value={1}>одна</option><option value={2}>две (например, бирка и коробка)</option><option value={3}>три и больше</option>
            </select>
          </>}
          <span>Образец артикула</span>
          <div className="row nowrap"><input type="text" maxLength={60} style={{ width: 180 }} placeholder="например BX096-2"
            value={r.article_example} onChange={(e) => set("article_example", e.target.value)} />
            <span className="hint">с бирки возьмётся код такого вида, остальные номера — пропустятся</span></div>
          {aiSort && <>
            <span>Разные товары</span>
            <div className="ch">
              <label className="check"><input type="checkbox" checked={r.colors_separate} onChange={(e) => set("colors_separate", e.target.checked)} />
                {" "}разные цвета одной модели — разные товары</label>
              <label className="check"><input type="checkbox" checked={r.sizes_together} onChange={(e) => set("sizes_together", e.target.checked)} />
                {" "}разные размеры одной модели — один товар</label>
            </div>
          </>}
          <span>Не принимать за артикул</span>
          <div className="row">
            {IGNORE.map(([k, name]) => (
              <label key={k} className="check"><input type="checkbox" checked={r.ignore.includes(k)}
                onChange={(e) => set("ignore", e.target.checked ? [...r.ignore, k] : r.ignore.filter((x) => x !== k))} /> {name}</label>
            ))}
          </div>
          {aiSort && <>
            <span>Упаковка</span>
            <label className="check"><input type="checkbox" checked={r.ignore.includes("packaging")}
              onChange={(e) => set("ignore", e.target.checked ? [...r.ignore, "packaging"] : r.ignore.filter((x) => x !== "packaging"))} />
              {" "}фото коробок и пакетов не брать в товар</label>
          </>}
          {aiSort && <>
            <span>Своё правило</span>
            <textarea className="short" maxLength={1000} value={r.rule}
              placeholder="Необязательно, словами. Например: «каждый товар — 4 фото подряд, затем бирка» или «детали крупным планом относятся к предыдущему товару»"
              onChange={(e) => set("rule", e.target.value)} />
          </>}
        </div>
        {changed && <button className="link mt6" onClick={() => onChange(DEFAULT_RULES)}>сбросить правила</button>}
      </details>
    </>
  );
}
