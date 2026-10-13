import type { Dialogs } from "../App";
import { api } from "../api/client";
import { useActions } from "../hooks/useActions";
import { useProject } from "../ProjectContext";
import { useUI } from "./ui";

/** Шапка страницы «Товары и кадры»: проект и главные действия. */
export function Header({ dialogs, onProjectsChanged }: { dialogs: Dialogs; onProjectsChanged: () => void }) {
  const { state, api: papi, selected, reload, run, limit } = useProject();
  const { generate } = useActions();
  const ui = useUI();
  const r = state.runner;

  const exportZip = async () => {
    const include = await ui.choose({
      title: "Скачать кадры",
      text: "Какие кадры положить в архив? В архиве — папки по артикулам и отчёт report.csv.",
      choices: [
        { value: "all", label: "Все готовые" },
        { value: "accepted", label: "Только принятые", primary: true },
      ],
    });
    if (!include) return;
    ui.toast("Готовлю архив…");
    window.location.href = papi.exportUrl(include);
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
      <span className="spacer" />
      {r.busy && (
        <span className="live" title="Задания в работе и в очереди">
          <i /> {r.stopping ? "останавливаю…" : `в работе ${r.running} · в очереди ${r.queued}`}
        </span>
      )}
      <button onClick={dialogs.openImport}>Загрузить фото</button>
      <button onClick={exportZip}>Скачать ZIP</button>
      <button className="primary" onClick={() => generate(selected.size ? [...selected] : null, limit)}>
        {selected.size ? `Запустить выбранные (${selected.size})` : "Запустить все"}
      </button>
      <button className="danger" disabled={!r.busy} onClick={stop}>Стоп</button>
    </div>
  );
}
