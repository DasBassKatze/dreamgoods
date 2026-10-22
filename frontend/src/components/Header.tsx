import type { Dialogs } from "../App";
import { api } from "../api/client";
import { Icon } from "../layout/Icon";
import { useProject } from "../ProjectContext";
import { setNotify, useNotifySwitch } from "../lib/notify";
import { useUI } from "./ui";

/** Шапка страницы «Товары и кадры»: проект и главные действия. */
export function Header({ dialogs, onProjectsChanged, query, onQuery }: {
  dialogs?: Dialogs; onProjectsChanged: () => void; query: string; onQuery: (q: string) => void;
}) {
  const { state, api: papi, selected, reload, run, pickedFrames } = useProject();
  const ui = useUI();
  const r = state.runner;
  const notify = useNotifySwitch();

  const toggleNotify = async () => {
    const res = await setNotify(!notify);
    ui.toast(res === "on" ? "Уведомления включены: когда кадры будут готовы — сигнал и уведомление, даже если вкладка свёрнута"
      : res === "off" ? "Уведомления о готовности выключены"
        : res === "denied" ? "Включён звуковой сигнал. Системные уведомления браузер запретил — их можно разрешить в настройках сайта (значок слева от адреса)"
          : res === "insecure" ? "Включён звуковой сигнал и счётчик во вкладке. Системные уведомления браузер даёт только сайтам по HTTPS"
            : "Включён звуковой сигнал и счётчик во вкладке — этот браузер не показывает системные уведомления", 7000);
  };

  const exportZip = async () => {
    const picked = pickedFrames.size;
    const products = selected.size;
    const include = await ui.choose<"accepted" | "all" | "picked">({
      title: "Скачать кадры",
      text: "«Принятые» — принятые вручную, прошедшие ИИ-проверку и кадры без проверки; кадры на ручной проверке (брак) — " +
        "только в «Все готовые». В архиве — папки по артикулам и report.csv, где перечислены и кадры, не попавшие в архив, с причиной." +
        (products && !picked ? ` Выгружаются только выбранные товары (${products}).` : "") +
        (!picked ? " Чтобы скачать отдельные кадры — отметьте их галочкой на плитке кадра (или Ctrl+клик)." : ""),
      choices: [
        ...(picked ? [{ value: "picked" as const, label: `Выделенные кадры (${picked})`, primary: true }] : []),
        { value: "all", label: products && !picked ? `Все готовые в выбранных` : "Все готовые" },
        { value: "accepted", label: products && !picked ? `Принятые в выбранных` : "Принятые", primary: !picked },
      ],
    });
    if (!include) return;
    ui.toast("Готовлю архив…");
    window.location.href = include === "picked"
      ? papi.exportUrl("picked", { frames: [...pickedFrames] })
      : papi.exportUrl(include, { products: picked ? [] : [...selected] });
  };

  const stop = () =>
    run(async () => {
      const ok = await ui.confirm({
        title: "Остановить генерацию?",
        text: "Кадры в очереди будут сняты, уже запущенные доделают текущую попытку (она оплачена).",
        ok: "Остановить",
      });
      if (!ok) return;
      await papi.stop();
      await reload();
    });

  const rename = () =>
    run(async () => {
      const v = await ui.ask({ title: "Переименовать проект", ok: "Сохранить", fields: [{ key: "name", label: "Название", value: state.project.name }] });
      if (!v) return;
      await api.renameProject(state.project.id, v.name);
      onProjectsChanged();
      await reload();
    });

  return (
    <div className="page-head products-head">
      <div className="ph-title">
        <h1><button className="title-btn" title="Переименовать" onClick={rename}>{state.project.name}</button></h1>
        {state.admin && <span className="hint">кабинет «{state.project.client}»</span>}
      </div>
      <label className="search-big">
        <Icon name="search" size={18} />
        <input type="search" placeholder="Поиск по артикулу или названию" value={query} onChange={(e) => onQuery(e.target.value)} />
      </label>
      {state.open_import && (
        <button className="resume-import" onClick={dialogs?.openImport}
          title="Фото уже загружены, но товары из них ещё не созданы — вернуться к загрузке и закончить раскладку">
          <Icon name="upload" size={16} /> Незавершённая загрузка · {state.open_import.count} фото
        </button>
      )}
      {r.busy && (
        <span className="live" title="Задания в работе и в очереди">
          <i /> {r.stopping ? "останавливаю…" : `в работе ${r.running} · в очереди ${r.queued}`}
        </span>
      )}
      <button className={`icon-btn notify-btn ${notify ? "on" : ""}`} onClick={toggleNotify}
        title={notify ? "Уведомления о готовности кадров включены — нажмите, чтобы выключить"
          : "Включить уведомления о готовности кадров (придут, даже если вкладка свёрнута)"}
        aria-label="Уведомления о готовности"><Icon name="bell" size={18} /></button>
      <button onClick={exportZip}><Icon name="download" size={16} /> Скачать ZIP</button>
      {r.busy && <button className="danger" onClick={stop}>Стоп</button>}
    </div>
  );
}
