import type { Dialogs } from "../App";
import { api } from "../api/client";
import { useActions } from "../hooks/useActions";
import { useProject } from "../ProjectContext";
import { useUI } from "./ui";

/** Шапка страницы «Товары и кадры»: проект и главные действия. */
export function Header({ dialogs, onProjectsChanged }: { dialogs: Dialogs; onProjectsChanged: () => void }) {
  const { state, api: papi, selected, reload, run, limit, pickedFrames } = useProject();
  const { generate } = useActions();
  const ui = useUI();
  const r = state.runner;

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
