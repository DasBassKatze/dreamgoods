import { useActions } from "../hooks/useActions";
import { useProject } from "../ProjectContext";
import { useUI } from "./ui";
import { Icon } from "../layout/Icon";

export type Filter = "all" | "todo" | "review" | "err";

/** Статус проекта + поиск + фильтры. */
export function Toolbar({ filter, onFilter }: { filter: Filter; onFilter: (f: Filter) => void }) {
  const { state } = useProject();
  const { totals: t, runner: r } = state;
  const todo = state.products.filter((p) => p.done < p.total).length;
  const FILTERS: [Filter, string, number | null][] = [
    ["all", "Все", state.products.length],
    ["todo", "Недоделанные", todo],
    ["review", "На проверке", t.review],
    ["err", "С ошибками", r.errors],
  ];
  return (
    <div className="bar">
      <div className="stat">
        <b>{t.done}</b><span>/ {t.total} кадров готово</span>
        <div className="progress"><i style={{ width: `${t.total ? (t.done / t.total) * 100 : 0}%` }} /></div>
      </div>
      <span className="spacer" />
      <span className="seg">
        {FILTERS.map(([k, name, n]) => (
          <button key={k} className={`${filter === k ? "on" : ""} ${k === "err" && n ? "has-err" : ""}`} onClick={() => onFilter(k)}>
            {name}{n ? <span className="cnt-pill">{n}</span> : null}
          </button>
        ))}
      </span>
    </div>
  );
}

/** Строка над списком: выбор товаров и групповые действия. */
export function ListBar() {
  const { state, api, reload, run, selected, setSelected, pickedFrames, setPicked } = useProject();
  const { checkReady, profiles } = useActions();
  const ui = useUI();
  const s = state.settings;
  const allIds = state.products.map((p) => p.id);
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id));

  const toggle = (key: "qc_enabled" | "qc_autoregen", on: boolean, msgOn: string, msgOff: string) =>
    run(async () => {
      await api.saveSettings({ [key]: on });
      ui.toast(on ? msgOn : msgOff);
      await reload();
    });

  const newProfiles = async () => {
    const n = state.products.filter((p) => !p.total).length;
    if (!n) {
      ui.toast("У всех товаров уже есть промпты");
      return;
    }
    if (await ui.confirm({ text: `Составить профиль товара и промпты по фото для ${n} товаров без промптов?`, ok: "Составить" })) {
      profiles(null, true);
    }
  };

  return (
    <div className="listbar">
      <label className="check">
        <input type="checkbox" checked={allSelected} onChange={(e) => setSelected(e.target.checked ? allIds : [])} />
        {selected.size ? <>выбрано <b>{selected.size}</b></> : "выбрать все"}
      </label>
      {selected.size > 0 && <button className="link" onClick={() => setSelected([])}>снять выбор</button>}
      {pickedFrames.size > 0 && (
        <span className="hint" title="Выделенные кадры можно скачать отдельно: «Скачать ZIP» → «Выделенные кадры»">
          кадров выделено <b>{pickedFrames.size}</b>{" "}
          <button className="link" onClick={() => setPicked([])}>снять</button>
        </span>
      )}
      <span className="spacer" />
      <button title="Прогнать ИИ-проверку по уже сгенерированным кадрам без новой генерации" onClick={checkReady}><Icon name="search" size={15} /> Проверить готовые</button>
      <button title="Для товаров без промптов: ИИ составит профиль товара по фото и промпты кадров" onClick={newProfiles}><Icon name="spark" size={15} /> Промпты для новых</button>
      <span className="toggles">
        <label className="switch" title="Проверять каждый кадр ИИ">
          <input type="checkbox" checked={s.qc_enabled}
            onChange={(e) => toggle("qc_enabled", e.target.checked, "ИИ-проверка включена", "ИИ-проверка выключена")} />
          <i /> ИИ-проверка
        </label>
        <label className="switch" title="Переделывать брак автоматически; выключено — брак сразу уходит в «На проверке»">
          <input type="checkbox" checked={s.qc_autoregen} disabled={!s.qc_enabled}
            onChange={(e) => toggle("qc_autoregen", e.target.checked, "Брак будет переделываться автоматически",
              "Брак не переделывается — сразу в «На проверке»")} />
          <i /> переделка брака
        </label>
      </span>
    </div>
  );
}
