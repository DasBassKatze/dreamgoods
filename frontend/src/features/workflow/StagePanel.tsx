import { useCallback, useEffect, useState } from "react";
import { assetUrl, type PreflightReport, type Trial } from "../../api/client";
import { parseBudget, budgetFields, EstimateText } from "../budgets/BudgetForm";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useGenerationSelection } from "../generate/GenerationSelection";
import { AdvancedFields } from "../interface/InterfaceMode";
import { useProject } from "../../ProjectContext";

export function StagePanel() {
  const { api, reload, run, state } = useProject();
  const ui = useUI();
  const [report, setReport] = useState<PreflightReport | null>(null);
  const [trial, setTrial] = useState<Trial | null>(null);
  const [busy, setBusy] = useState(false);
  const { ids, label } = useGenerationSelection();
  const refresh = useCallback(async () => { const r = await api.trial(); setTrial(r.trial); }, [api]);
  useEffect(() => {
    let alive = true;
    const load = async () => { if (!document.hidden) { try { const r = await api.trial(); if (alive) setTrial(r.trial); } catch { /* основной экран показывает связь */ } } };
    void load();
    const timer = window.setInterval(load, 15000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [api, state.runner.busy]);
  const action = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try { await run(fn); } finally { setBusy(false); }
  };
  const sample = () => action(async () => {
    const r = await api.preflight(ids);
    if (r.errors || r.products.some((p) => p.issues.some((i) => i.code === "no_profile" || i.code === "no_frames"))) {
      setReport(r); return;
    }
    if (!await ui.confirm({ title: "Пробная съёмка", text: "Снять один кадр первого товара из выбранной партии? Это платная генерация с обычной ИИ-проверкой, без автоматических переделок. Остальные кадры пока не запускаются.", ok: "Снять один кадр" })) return;
    const result = await api.startTrial(ids);
    setTrial(result.trial); await reload();
  });
  const approve = () => action(async () => {
    if (!trial?.generation) return;
    const estimate = await api.estimateTrial(trial.id);
    const limits = await ui.ask({title:"Утвердить и запустить партию",text:<><p>Запустить недостающие кадры {trial.products} товар(ов) сохранённой партии?</p><EstimateText estimate={estimate} /></>, fields:budgetFields(estimate.reserve_upper),ok:"Утвердить и запустить"});
    if (!limits) return;
    const r = await api.approveTrial(trial.id, trial.generation,parseBudget(limits));
    ui.toast(r.already_approved ? "Эта партия уже утверждена" : `В очередь добавлено кадров: ${r.added}`);
    await refresh(); await reload();
  });
  const product = trial && state.products.find((p) => p.id === trial.product_id);
  return <section className="stage-panel"><AdvancedFields title="Проверка исходников и пробный кадр" summary={trial && !trial.approved ? "Есть пробная съёмка — результат ниже" : "Перед запуском большой партии"}>
    <div className="row wrap"><b>Перед большой партией</b><span className="spacer" />
      <button disabled={busy || !ids.length} onClick={() => action(async () => setReport(await api.preflight(ids)))}>Проверить исходники · бесплатно</button>
      <button disabled={busy || !ids.length} onClick={sample}>Пробный кадр · платно</button>
      <a href="#/review">Перейти к приёмке →</a>
    </div>
    <p className="hint">Проверьте фото, снимите один кадр и утвердите результат перед запуском остальных. Область проверки и пробной съёмки: {label}.</p>
    </AdvancedFields>
    {trial && !trial.approved && <div className="trial-card">
      {trial.asset && <button className="trial-preview" onClick={() => ui.zoom([assetUrl(trial.asset!)])}><img src={assetUrl(trial.asset, 600)} alt={`Пробный кадр ${product?.sku ?? ""}`} /></button>}
      <div><b>Пробная партия · {trial.products} товар(ов)</b><p>{trial.asset ? "Пробный кадр готов. Оцените товар, свет и композицию." : trial.status === "error" ? "Пробная съёмка завершилась с ошибкой." : "Пробный кадр готовится…"}</p>
      {trial.error && <p className="error">{trial.error}</p>}
      <button className="primary" disabled={busy || !trial.generation || trial.status !== "done"} onClick={approve}>Утвердить и запустить партию</button>
      <p className="hint">Продолжение относится к сохранённому составу партии. Изменение выбора сверху её не меняет.</p></div>
    </div>}
    {trial?.approved && <p className="hint">Пробная партия утверждена. Остальные кадры поставлены в очередь.</p>}
    {report && <Modal title="Проверка исходников" width={850} onClose={() => setReport(null)}>
      <div className="preflight-body"><p>{report.note}</p>
        <p>Товаров: {report.products.length} · с ошибками: {report.errors} · с предупреждениями: {report.warnings}</p>
        {report.products.length === 0 && <p>Добавьте товары в проект.</p>}
        {report.products.map((p) => <article key={p.id} className="preflight-product"><b>{p.sku}</b><span> · референсов: {p.references}</span>
          {p.issues.length ? <ul>{p.issues.map((i, n) => <li key={n} className={`preflight-${i.level}`}>{i.level === "error" ? "Ошибка: " : i.level === "warning" ? "Проверьте: " : ""}{i.text}</li>)}</ul> : <p>В сохранённых данных проблем не найдено.</p>}
        </article>)}
        {report.products.some((p) => p.issues.some((i) => i.code === "no_profile" || i.code === "no_frames")) && <button disabled={busy} onClick={() => action(async () => {
          const productIds = report.products.filter((p) => p.issues.some((i) => i.code === "no_profile" || i.code === "no_frames")).map((p) => p.id);
          if (!await ui.confirm({title:"Подготовить профили",text:`ИИ составит профили и план кадров ${productIds.length} товар(ов). Анализ фото платный; генерация изображений автоматически не запускается.`,ok:"Подготовить"})) return;
          await api.generateProfiles(productIds, true); setReport(null); await reload(); ui.toast("Подготовка профилей поставлена в очередь");
        })}>Подготовить профили и план кадров…</button>}
      </div>
    </Modal>}
  </section>;
}
