import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { AdminOverview, ModerationEvent } from "../../api/types";
import { Icon } from "../../layout/Icon";
import { Modal } from "../../components/Modal";
import { MetricsPanel } from "../../components/MetricsPanel";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";
import { useProject } from "../../ProjectContext";

type Tab = "overview" | "spend" | "quality" | "models" | "moderation" | "log";
const TABS: [Tab, string][] = [
  ["overview", "Обзор"], ["spend", "Расходы проекта"], ["quality", "Качество"], ["models", "Модели по блокам"],
  ["moderation", "Модерация"],
];
const BLOCK_RU: Record<string, string> = { studio: "Товар на фоне", detail: "Детали", worn: "На человеке", full: "В полный рост", lifestyle: "Лайфстайл" };

/** Админ-панель: всё про деньги, качество и технику. Рядовой пользователь её не видит. */
export function AdminPanel({ onCatalog, logOnly }: { onCatalog: () => void; logOnly?: boolean }) {
  const { state } = useProject();
  const ui = useUI();
  const [tab, setTab] = useState<Tab>(logOnly ? "log" : "overview");
  const [o, setO] = useState<AdminOverview | null>(null);
  const [exportOpen, setExportOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setO(await adminApi.overview(state.project.id));
    } catch (e) {
      ui.toast((e as Error).message);
    }
  }, [state.project.id, ui]);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, [load]);

  return (
    <section className="page">
      <div className="page-head">
        <h1>{logOnly ? "Журнал сервера" : "Аналитика проекта"}</h1>
        {!logOnly && <span className="hint">проект «{state.project.name}» · {state.project.client}</span>}
        {!logOnly && <><span className="spacer" />
          <button onClick={() => setExportOpen(true)}><Icon name="download" size={16} /> Выгрузить данные проверки</button></>}
      </div>
      {exportOpen && <QcExport projectId={state.project.id} projectName={state.project.name} onClose={() => setExportOpen(false)} />}
      {!logOnly && (
        <div className="tabs">
          {TABS.map(([k, name]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{name}</button>)}
        </div>
      )}
      {!o ? <div className="empty">Загрузка…</div> : (
        <>
          {o.default_password && (
            <div className="warns">У мастер-аккаунта стандартный пароль «admin». Смените его в разделе «Учётная запись».</div>
          )}
          {tab === "overview" && <Overview o={o} reload={load} onCatalog={onCatalog} />}
          {tab === "spend" && <Spend o={o} />}
          {tab === "quality" && <MetricsPanel m={o.metrics} />}
          {tab === "models" && <ModelStats o={o} />}
          {tab === "log" && <ServerLog />}
          {tab === "moderation" && <ModerationLog />}
        </>
      )}
    </section>
  );
}

function Kpi({ label, value, hint, warn }: { label: string; value: string | number; hint?: string; warn?: boolean }) {
  return (
    <div className={`kpi ${warn ? "warn" : ""}`}>
      <small>{label}</small>
      <b>{value}</b>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function Overview({ o, reload, onCatalog }: { o: AdminOverview; reload: () => Promise<void>; onCatalog: () => void }) {
  const ui = useUI();
  const { state } = useProject();
  const [par, setPar] = useState(o.queue.parallel);
  useEffect(() => setPar(o.queue.parallel), [o.queue.parallel]);

  const saveParallel = async () => {
    try {
      const r = await adminApi.setParallel(par);
      ui.toast(`Одновременных заданий: ${r.parallel}`);
      await reload();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };
  const resume = async () => {
    try {
      const r = await adminApi.resume();
      ui.toast(r.resumed ? `Дозагружено результатов: ${r.resumed}` : "Polza ещё не отдала результаты — проверю снова через минуту");
      await reload();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  return (
    <>
      <div className="kpis">
        <Kpi label="Баланс Polza" value={o.balance == null ? "—" : rub(o.balance)} hint={o.balance_error || undefined} warn={!!o.balance_error} />
        <Kpi label="Расход с запуска" value={rub(o.spent.session)} />
        <Kpi label="Расход по проекту" value={rub(o.spent.project)} hint={`${state.project.client} · ${state.project.name}`} />
        <Kpi label="Расход всего" value={rub(o.spent.org)} hint="по всем клиентам" />
        <Kpi label="Средняя генерация" value={rub(o.generations.avg_cost)} hint={`${o.generations.count} шт. · ≈ ${o.generations.avg_seconds} с`} />
        <Kpi label="Цена принятого кадра" value={rub(o.metrics.cost_per_accepted)} />
        <Kpi label="Ошибок за сутки" value={o.errors_24h} warn={o.errors_24h > 0} />
        <Kpi label="Ждут дозагрузки" value={o.pending} hint="оплаченные задачи Polza, результат не получен" warn={o.pending > 0} />
      </div>

      <div className="admin-grid">
        <section className="panel">
          <h3>Связь с Polza и очередь</h3>
          <div className="hint">Генерации идут параллельно. Каждая задача Polza получает номер сразу после отправки — при обрыве
            связи, перезапуске или долгом ожидании результат дозагружается автоматически без повторной оплаты.</div>
          <div className="row">
            <span>Одновременных заданий:</span>
            <input type="range" min={1} max={o.queue.max} value={par} onChange={(e) => setPar(+e.target.value)} />
            <b style={{ width: 24 }}>{par}</b>
            <button className="primary" disabled={par === o.queue.parallel} onClick={saveParallel}>Применить</button>
          </div>
          <div className="hint mt4">Потоки почти ничего не стоят: пока Polza рисует, поток спит, а статусы проверяет общий опросчик.
            Скорость отправки сервис подбирает сам — растёт, пока Polza отвечает, и снижается при «занято» (HTTP 429).</div>
          <div className="met mt8">
            <div><span>Заданий: в работе / в очереди</span><b>{o.queue.running} / {o.queue.queued}</b></div>
            <div><span>Ждут результат у Polza</span><b>{o.queue.waiting_polza}</b></div>
            <div><span>Скорость отправки задач</span><b>{o.queue.limits.submit_rate != null ? `${o.queue.limits.submit_rate} в сек.` : "—"}</b></div>
            <div><span>Отказов «занято» за час</span><b className={o.queue.limits.throttled_hour ? "bad-text" : ""}>{o.queue.limits.throttled_hour}</b></div>
          </div>
          <div className="row">
            <button disabled={!o.pending} onClick={resume}>⤵ Дозагрузить сейчас ({o.pending})</button>
          </div>
        </section>
        <section className="panel">
          <h3>Модели</h3>
          <div className="met">
            <div><span>Генерация</span><b>{o.model.model}</b></div>
            <div className="sub"><span>провайдер · разрешение · формат</span><span>{o.model.providers || "авто"} · {o.model.resolution} · {o.model.aspect}</span></div>
            <div><span>ИИ-проверка</span><b>{o.model.qc_model}</b></div>
          </div>
          <div className="row"><button onClick={onCatalog}>Каталог моделей Polza</button></div>
        </section>
      </div>
    </>
  );
}

function Bars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.label} className="bar-row">
          <span className="bl">{r.label}</span>
          <span className="bt"><i style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <b>{rub(r.value)}</b>
        </div>
      ))}
    </div>
  );
}

function Spend({ o }: { o: AdminOverview }) {
  return (
    <div className="admin-grid">
      <section className="panel">
        <h3>По видам операций</h3>
        <Bars rows={o.by_kind.map((x) => ({ label: `${x.name} · ${x.calls}`, value: x.sum }))} />
      </section>
      <section className="panel">
        <h3>По дням (14 дней)</h3>
        {o.by_day.length ? <Bars rows={o.by_day.map((x) => ({ label: new Date(x.day).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }), value: x.sum }))} />
          : <div className="hint">Расходов за две недели нет</div>}
      </section>
      <section className="panel wide">
        <h3>По моделям</h3>
        <table className="tbl">
          <thead><tr><th>Модель</th><th>Запросов</th><th>Сумма</th><th>В среднем</th></tr></thead>
          <tbody>{o.by_model.map((x) => (
            <tr key={x.model}><td>{x.model}</td><td>{x.calls}</td><td>{rub(x.sum)}</td><td>{rub(x.avg)}</td></tr>
          ))}</tbody>
        </table>
      </section>
    </div>
  );
}

function ModelStats({ o }: { o: AdminOverview }) {
  if (!o.model_stats.length) return <div className="empty">Пока нет сгенерированных кадров</div>;
  return (
    <>
      <div className="hint mb10">Как модели справляются с каждым блоком кадров (по всем клиентам). Если дешёвая модель проходит
        проверку с первой попытки не хуже дорогой — поставьте её на этот блок в пресете.</div>
      <table className="tbl">
        <thead><tr><th>Блок</th><th>Модель</th><th>Кадров</th><th>С 1-й попытки</th><th>Средняя цена</th></tr></thead>
        <tbody>{o.model_stats.map((x) => (
          <tr key={x.block + x.model}><td>{BLOCK_RU[x.block] || x.block}</td><td>{x.model}</td><td>{x.n}</td>
            <td>{x.first_pass == null ? "—" : `${x.first_pass}%`}</td><td>{rub(x.avg_cost)}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

function ServerLog() {
  const ui = useUI();
  const [lines, setLines] = useState<string[] | null>(null);
  const [level, setLevel] = useState("");
  const load = useCallback(async () => {
    try {
      setLines((await adminApi.log(500, level)).lines);
    } catch (e) {
      ui.toast((e as Error).message);
    }
  }, [level, ui]);
  useEffect(() => {
    load();
  }, [load]);
  return (
    <>
      <div className="row nowrap mb10">
        <span className="seg">
          <button className={level === "" ? "on" : ""} onClick={() => setLevel("")}>Всё</button>
          <button className={level === "warning" ? "on" : ""} onClick={() => setLevel("warning")}>Предупреждения и ошибки</button>
        </span>
        <span className="spacer" />
        <button onClick={load}>↻ Обновить</button>
      </div>
      <div className="log server-log">
        {lines == null ? "Загрузка…" : !lines.length ? <div className="hint">Пусто</div> : [...lines].reverse().map((l, n) => (
          <div key={n} className={/ ERROR /.test(l) ? "err" : / WARNING /.test(l) ? "warn" : ""}>{l}</div>
        ))}
      </div>
    </>
  );
}

/** Выгрузка данных ИИ-проверки (ZIP): проверки, ручные решения, профили товаров, картинки спорных кадров. */
function QcExport({ projectId, projectName, onClose }: { projectId: number; projectName: string; onClose: () => void }) {
  const [scope, setScope] = useState<"project" | "all">("project");
  const [days, setDays] = useState(0);
  const [images, setImages] = useState<"none" | "disputed" | "all">("disputed");
  const url = adminApi.qcExportUrl({ project: scope === "project" ? projectId : null, days: days || null, images });
  const ui = useUI();
  const [busy, setBusy] = useState(false);
  // архив с картинками собирается до минуты — качаем через fetch, чтобы показать, что идёт работа
  const download = async () => {
    setBusy(true);
    try {
      const r = await fetch(url, { credentials: "same-origin" });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || `ошибка ${r.status}`);
      const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") || "")?.[1] || "dreamgoods_qc.zip";
      const href = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = href;
      a.download = name;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(href), 5000);
      onClose();
    } catch (e) {
      ui.toast((e as Error).message, 5000);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="Выгрузка данных проверки" width={560} onClose={onClose}
      footer={<><span className="spacer" /><button onClick={onClose}>Закрыть</button>
        <button className="primary" onClick={download} disabled={busy}>
          <Icon name="download" size={16} /> {busy ? "Собираю архив…" : "Скачать ZIP"}</button></>}>
      <div className="form grid">
        <label className="form-label" htmlFor="qe-scope">Что выгрузить</label>
        <select id="qe-scope" value={scope} onChange={(e) => setScope(e.target.value as "project" | "all")}>
          <option value="project">Проект «{projectName}»</option>
          <option value="all">Все проекты сервиса</option>
        </select>
        <label className="form-label" htmlFor="qe-days">Период</label>
        <select id="qe-days" value={days} onChange={(e) => setDays(+e.target.value)}>
          <option value={0}>За всё время</option>
          <option value={7}>Последние 7 дней</option>
          <option value={30}>Последние 30 дней</option>
          <option value={90}>Последние 90 дней</option>
        </select>
        <label className="form-label" htmlFor="qe-img">Картинки</label>
        <select id="qe-img" value={images} onChange={(e) => setImages(e.target.value as "none" | "disputed" | "all")}>
          <option value="disputed">Брак и кадры, где вы не согласились с ИИ</option>
          <option value="all">Все проверенные кадры (до 400)</option>
          <option value="none">Без картинок — только таблицы</option>
        </select>
      </div>
      <p className="hint mt12">В архиве: таблица всех проверок с причинами брака и промптами, ваши ручные решения, профили товаров
        и описание фото товаров. Ключей, паролей и балансов в выгрузке нет. Таблицы открываются в Excel.
        С картинками архив собирается до минуты.</p>
    </Modal>
  );
}

const SOURCE_RU: Record<ModerationEvent["source"], string> = { text: "запрос", frame: "готовый кадр", photo: "загруженное фото" };
const ACTION_RU: Record<ModerationEvent["action"], string> = { blocked: "не выполнено", rejected: "отклонено", hidden: "скрыто" };

/** Журнал модерации (весь сервис): что остановлено — запросы, готовые кадры, загруженные фото. */
function ModerationLog() {
  const ui = useUI();
  const [items, setItems] = useState<ModerationEvent[] | null>(null);
  useEffect(() => {
    adminApi.moderation().then((r) => setItems(r.items)).catch((e) => ui.toast((e as Error).message));
  }, [ui]);
  if (!items) return <div className="empty">Загрузка…</div>;
  return (
    <div className="panel">
      <p className="hint">Сервис не выполняет запросы и не показывает кадры с содержанием, запрещённым в РФ: символика ЛГБТ
        и экстремистских организаций, нацистская символика, наркотики, обнажёнка, сексуализация несовершеннолетних,
        дискредитация армии. Здесь — все такие случаи по всем кабинетам (последние 300).</p>
      {!items.length ? <div className="empty">Пока ничего не останавливалось.</div> : (
        <div className="table-wrap"><table className="tbl">
          <thead><tr><th>Когда</th><th>Кабинет · проект</th><th>Где</th><th>Что найдено</th><th>Итог</th></tr></thead>
          <tbody>{items.map((e) => (
            <tr key={e.id}>
              <td className="hint nowrap">{e.created ? new Date(e.created).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</td>
              <td>{e.client || "—"}<div className="hint">{e.project}{e.user ? ` · ${e.user}` : ""}</div></td>
              <td>{SOURCE_RU[e.source] || e.source}<div className="hint">{e.where}</div></td>
              <td><b>{e.category_name}</b><div className="hint">{e.excerpt}</div></td>
              <td className="nowrap">{ACTION_RU[e.action] || e.action}</td>
            </tr>))}
          </tbody></table></div>
      )}
    </div>
  );
}
