import { usePersistentState } from "../hooks/usePersistentState";
import { useProject } from "../ProjectContext";

/** Лента событий проекта (у рядового пользователя — без сумм и технических подробностей). */
export function LogPanel() {
  const { state, api, reload, run } = useProject();
  const [open, setOpen] = usePersistentState("log_open", false);
  const lines = [...state.log].reverse();
  return (
    <div className={`panel log-panel ${open ? "" : "closed"}`}>
      <div className="row panel-h">
        <h3><button aria-expanded={open} className="link" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} Лента событий</button></h3>
        <span className="spacer" />
        {open && state.runner.errors > 0 && (
          <button className="small" onClick={() => run(async () => { await api.clearErrors(); await reload(); })}>
            Скрыть ошибки ({state.runner.errors})
          </button>
        )}
      </div>
      {open && (
        <div className="log">
          {lines.length ? (
            lines.map((l, n) => (
              <div key={`${l.t}-${n}-${l.text.length}`} className={l.kind}>
                <span className="t">{l.t}</span>
                {l.text}
              </div>
            ))
          ) : (
            <div className="hint">Пока пусто</div>
          )}
        </div>
      )}
    </div>
  );
}
