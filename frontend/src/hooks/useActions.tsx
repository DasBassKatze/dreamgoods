import type { Frame, Product } from "../api/types";
import { useUI } from "../components/ui";
import { pad, rub } from "../lib/format";
import { useProject } from "../ProjectContext";

/** Действия запуска с подтверждением и оценкой цены — общие для шапки, карточек и просмотра кадра. */
export function useActions() {
  const { api, state, reload, selected, run } = useProject();
  const ui = useUI();

  const generate = (productIds: number[] | null, limit = 0) =>
    run(async () => {
      const p = await api.previewGenerate({ product_ids: productIds, limit });
      if (!p.count) {
        ui.toast("Всё уже сгенерировано");
        return;
      }
      const s = state.settings;
      const avg = state.totals.avg_cost;
      const est = avg ? ` (≈ ${rub(p.count * avg)} по средней цене кадра ${rub(avg)})` : "";
      const qc = !s.qc_enabled
        ? ""
        : s.qc_autoregen && s.qc_retries > 0
          ? `ИИ-проверка и автоперегенерация включены: брак переделывается до ${s.qc_retries} раз(а), поэтому в худшем случае расход вырастет до ×${1 + s.qc_retries}.`
          : "ИИ-проверка включена, автоперегенерация выключена: брак не переделывается, а сразу попадает в «На проверке».";
      const ok = await ui.confirm({
        title: "Запуск генерации",
        text: <>Сгенерировать {p.count} кадр(ов){est}?{qc && <p className="hint">{qc}</p>}</>,
        ok: "Запустить",
      });
      if (!ok) return;
      const r = await api.generate({ product_ids: productIds, limit });
      ui.toast(`В очередь добавлено: ${r.added}`);
      await reload();
    });

  const regenerate = (product: Product, frame: Frame, askFirst = true) =>
    run(async () => {
      if (askFirst && frame.asset) {
        const ok = await ui.confirm({
          text: `Перегенерировать кадр ${pad(frame.i)} товара ${product.sku}? Текущий вариант сохранится в истории.`,
          ok: "Перегенерировать",
        });
        if (!ok) return;
      }
      const r = await api.generate({ frame_ids: [frame.id] });
      ui.toast(r.added ? "Кадр поставлен в очередь" : "Кадр уже в очереди");
      await reload();
    });

  const checkReady = () =>
    run(async () => {
      const product_ids = selected.size ? [...selected] : null;
      const p = await api.previewCheck({ product_ids, only_unchecked: true });
      if (!p.count) {
        ui.toast("Непроверенных готовых кадров нет");
        return;
      }
      const ok = await ui.confirm({
        title: "ИИ-проверка готовых кадров",
        text: `Проверить ИИ ${p.count} готовых кадр(ов)${selected.size ? " в выбранных товарах" : ""}? Генерации не будет, оплачивается только проверка.`,
        ok: "Проверить",
      });
      if (!ok) return;
      const r = await api.check({ product_ids, only_unchecked: true });
      ui.toast(`На проверку: ${r.added}`);
      await reload();
    });

  const profiles = (productIds: number[] | null, build: boolean) =>
    run(async () => {
      const r = await api.generateProfiles(productIds, build);
      ui.toast(r.added ? "ИИ смотрит на фото и составляет профиль…" : "Профиль уже составляется");
      await reload();
    });

  return { generate, regenerate, checkReady, profiles };
}
