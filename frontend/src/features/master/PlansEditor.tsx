import { useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { PlansAdmin, PricePlan, QualityLevel } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";

type Row = { key: keyof PricePlan; label: string; kind: "text" | "money" | "num" | "limit" | "bool" | "qualities" };

// строки редактора: что настраивается у каждого тарифа
const ROWS: Row[] = [
  { key: "name", label: "Название", kind: "text" },
  { key: "price", label: "Платёж в месяц, ₽ (идёт на баланс)", kind: "money" },
  { key: "who", label: "Для кого (подпись на сайте)", kind: "text" },
  { key: "qualities", label: "Уровни качества", kind: "qualities" },
  { key: "parallel", label: "Генераций одновременно", kind: "num" },
  { key: "storage_gb", label: "Хранилище, ГБ", kind: "num" },
  { key: "projects", label: "Проектов", kind: "limit" },
  { key: "presets", label: "Своих пресетов", kind: "limit" },
  { key: "personas", label: "Своих моделей-людей", kind: "limit" },
  { key: "styles", label: "Оформлений по примеру", kind: "limit" },
  { key: "users", label: "Пользователей в кабинете", kind: "limit" },
  { key: "category_apply", label: "Пресеты по категориям", kind: "bool" },
  { key: "strictness", label: "Выбор строгости проверки", kind: "bool" },
  { key: "manual_plan", label: "Ручной план кадров", kind: "bool" },
  { key: "block_models", label: "Модель на блок кадров", kind: "bool" },
  { key: "custom_market", label: "Своя площадка", kind: "bool" },
  { key: "support", label: "Поддержка", kind: "text" },
];

/** Мастер: условия тарифов. Хранятся отличия от значений по умолчанию — «Сбросить» возвращает исходные. */
export function PlansEditor({ onClose }: { onClose: () => void }) {
  const ui = useUI();
  const [data, setData] = useState<PlansAdmin | null>(null);
  const [plans, setPlans] = useState<PricePlan[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminApi.plans().then((d) => { setData(d); setPlans(d.plans); }).catch((e) => ui.toast((e as Error).message));
  }, [ui]);

  const set = (i: number, key: keyof PricePlan, v: unknown) =>
    setPlans((ps) => ps.map((p, j) => (j === i ? { ...p, [key]: v } : p)));

  const save = async (reset = false) => {
    setBusy(true);
    try {
      const body = reset ? {} : Object.fromEntries(plans.map((p) => [p.key, p as unknown as Record<string, unknown>]));
      const d = await adminApi.savePlans(body);
      setData(d);
      setPlans(d.plans);
      ui.toast(reset ? "Условия тарифов сброшены к исходным" : "Условия тарифов сохранены — сайт и лимиты уже по ним");
    } catch (e) {
      ui.toast((e as Error).message, 5000);
    } finally {
      setBusy(false);
    }
  };

  const cell = (p: PricePlan, i: number, r: Row) => {
    const v = p[r.key];
    if (r.kind === "bool") return <input type="checkbox" checked={!!v} onChange={(e) => set(i, r.key, e.target.checked)} />;
    if (r.kind === "qualities") {
      const qs = p.qualities;
      return (
        <div className="q-pills">{(Object.keys(data?.quality_names || {}) as QualityLevel[]).map((q) => (
          <label key={q} className="check small"><input type="checkbox" checked={qs.includes(q)}
            onChange={(e) => set(i, "qualities", e.target.checked ? [...qs, q] : qs.filter((x) => x !== q))} />
            {" "}{data?.quality_names[q]}</label>))}</div>
      );
    }
    if (r.kind === "text") return <input type="text" value={String(v ?? "")} onChange={(e) => set(i, r.key, e.target.value)} />;
    const unlimited = r.kind === "limit" && v === null;
    return (
      <input type="number" min={0} value={unlimited ? "" : String(v ?? 0)} placeholder={r.kind === "limit" ? "∞" : ""}
        onChange={(e) => set(i, r.key, e.target.value === "" && r.kind === "limit" ? null : Math.max(0, +e.target.value || 0))} />
    );
  };

  const changed = (p: PricePlan, k: keyof PricePlan) =>
    data ? JSON.stringify(p[k]) !== JSON.stringify(data.defaults[p.key]?.[k]) : false;

  return (
    <Modal title="Условия тарифов" width={1000} onClose={onClose}
      footer={<>
        <button onClick={() => save(true)} disabled={busy}>Сбросить к исходным</button>
        <span className="spacer" />
        <button onClick={onClose}>Закрыть</button>
        <button className="primary" onClick={() => save()} disabled={busy || !plans.length}>Сохранить</button>
      </>}>
      <p className="hint">Изменения сразу действуют на сайте («Цены и оплата») и в лимитах кабинетов. Пустое поле в лимите — без
        ограничений, 0 — недоступно. Цена кадра от тарифа не зависит. Изменённые значения подсвечены.</p>
      {!plans.length ? <p className="hint">Загружаю…</p> : (
        <div className="table-wrap"><table className="tbl plans-edit">
          <thead><tr><th />{plans.map((p) => <th key={p.key}>{p.name}</th>)}</tr></thead>
          <tbody>{ROWS.map((r) => (
            <tr key={r.key}><td>{r.label}</td>
              {plans.map((p, i) => <td key={p.key} className={changed(p, r.key) ? "changed" : ""}>{cell(p, i, r)}</td>)}</tr>
          ))}</tbody>
        </table></div>
      )}
    </Modal>
  );
}
