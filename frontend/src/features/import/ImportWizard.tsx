import { useEffect, useRef, useState } from "react";
import type { ImportGroup, ImportResult, ImportView, PhotoRole } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";
import type { PickedFile } from "./files";
import { GroupsStep } from "./GroupsStep";
import { importModes, UploadStep, type ImportOptions } from "./UploadStep";

type Step = "upload" | "analyzing" | "groups" | "done";

/** Окно импорта держит своё состояние, пока проект открыт: можно закрыть и вернуться к раскладке. */
export function ImportWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { api, state, reload } = useProject();
  const ui = useUI();
  const [sid, setSid] = useState<number | null>(null);
  const [step, setStep] = useState<Step>("upload");
  const [total, setTotal] = useState(0);
  const [uploading, setUploading] = useState(0);
  const [opts, setOpts] = useState<ImportOptions>({ ai_sort: true, read_labels: true, auto_profile: true, sort_rule: "" });
  const modes = importModes(opts);
  const [view, setView] = useState<ImportView | null>(null);
  const [groups, setGroups] = useState<ImportGroup[]>([]);
  const [roles, setRoles] = useState<Record<string, PhotoRole>>({});
  const [result, setResult] = useState<ImportResult | null>(null);
  const poll = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(poll.current), []);

  // незавершённая загрузка (окно закрыли, страницу обновили) — продолжаем с того же места
  const resumed = useRef(false);
  useEffect(() => {
    const oi = state.open_import;
    if (resumed.current || !open || sid != null || !oi) return;
    resumed.current = true;
    setSid(oi.id);
    setTotal(oi.count);
    if (oi.status === "analyzing" || oi.status === "ready") {
      setStep("analyzing");
      watch(oi.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, state.open_import]);

  const restart = async () => {
    if (sid == null) return;
    if (!(await ui.confirm({ title: "Начать загрузку заново?", text: `Загруженные фото (${total}) не попадут в товары — их нужно будет загрузить снова.`, ok: "Начать заново" }))) return;
    try {
      await api.cancelImport(sid);
    } catch (e) {
      ui.toast((e as Error).message);
      return;
    }
    window.clearTimeout(poll.current);
    setSid(null); setTotal(0); setView(null); setGroups([]); setRoles({}); setStep("upload");
    await reload();
  };

  const ensure = async () => {
    if (sid != null) return sid;
    const r = await api.newImport();
    setSid(r.id);
    return r.id;
  };

  const upload = async (list: PickedFile[]) => {
    if (!list.length) return;
    let id: number;
    try {
      id = await ensure();
    } catch (e) {
      ui.toast((e as Error).message);
      return;
    }
    setUploading((n) => n + list.length);
    let i = 0, failed = 0;
    const worker = async () => {
      while (i < list.length) {
        const it = list[i++];
        try {
          const r = await api.uploadImportFile(id, it.path, it.file);
          setTotal((t) => Math.max(t, r.total));
        } catch {
          failed++;
        } finally {
          setUploading((n) => n - 1);
        }
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (failed) ui.toast(`Не загрузились: ${failed}`);
  };

  const watch = async (id: number) => {
    window.clearTimeout(poll.current);
    try {
      const v = await api.getImport(id);
      setView(v);
      if (v.status === "analyzing") {
        poll.current = window.setTimeout(() => watch(id), 1500);
        return;
      }
      if (v.status === "error") {
        setStep("upload");
        ui.toast("Ошибка анализа: " + v.error, 6000);
        return;
      }
      if (v.status === "ready") {
        setGroups(v.groups.map((g) => ({ ...g, photos: [...g.photos] })));
        const r: Record<string, PhotoRole> = {};
        v.photos.forEach((p) => (r[p.name] = p.role));
        v.groups.filter((g) => g.junk).forEach((g) => g.photos.forEach((n) => (r[n] = "junk")));
        setRoles(r);
        setStep("groups");
      }
    } catch {
      poll.current = window.setTimeout(() => watch(id), 3000);
    }
  };

  const analyze = async () => {
    if (sid == null) return;
    try {
      await api.analyzeImport(sid, modes.group_mode, modes.label_mode, opts.ai_sort ? opts.sort_rule.trim() : "");
      setStep("analyzing");
      setView(null);
      watch(sid);
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  const apply = async () => {
    if (sid == null) return;
    const real = groups
      .filter((g) => !g.junk && g.photos.length)
      .map((g) => ({ name: g.name.trim(), photos: g.photos.map((n) => [n, roles[n] || "product"] as [string, PhotoRole]),
        description: (g.description || "").trim(), sort_error: !!g.sort_error }));
    const names = real.map((g) => g.name.toLowerCase());
    if (names.some((n, i) => !n || names.indexOf(n) !== i)) {
      ui.toast("У групп должны быть разные непустые названия");
      return;
    }
    const empty = real.filter((g) => !g.photos.some(([, r]) => r !== "label" && r !== "junk"));
    const ok = await ui.confirm({
      title: "Создать товары",
      text: <>Создать или дополнить {real.length} товаров в проекте «{state.project.client} · {state.project.name}»?
        {empty.length > 0 && <p className="hint">Без фото товара (будут пропущены): {empty.map((g) => g.name).join(", ")}</p>}</>,
      ok: "Создать",
    });
    if (!ok) return;
    try {
      // бирки (найденные ИИ или отмеченные вручную) сохраняются у товара отдельно и в генерацию не идут
      const r = await api.applyImport(sid, real, "read", opts.auto_profile);
      setResult(r);
      setStep("done");
      setSid(null);
      setTotal(0);
      setView(null);
      await reload();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  const finish = () => {
    setStep("upload");
    setResult(null);
    onClose();
  };

  if (!open) return null;
  const progress = view?.progress;
  return (
    <Modal title={<>Загрузка фото{sid != null && <span className="hint"> · сессия {sid}</span>}</>} width={1280}
      onClose={step === "done" ? finish : onClose}>
      {step === "upload" && (
        <UploadStep total={total} uploading={uploading} options={opts} onOptions={setOpts} onFiles={upload} onAnalyze={analyze}
          onRestart={sid != null && total > 0 ? restart : undefined} />
      )}
      {step === "analyzing" && (
        <div className="empty">
          <div className="pbusy">
            {progress && progress[1] ? `ИИ смотрит фото: лист ${progress[0]} из ${progress[1]}…` : "Готовлю фото…"}
          </div>
          <div className="progress wide"><i style={{ width: `${progress && progress[1] ? (progress[0] / progress[1]) * 100 : 3}%` }} /></div>
        </div>
      )}
      {step === "groups" && view && (
        <GroupsStep view={view} groups={groups} roles={roles} labelMode={modes.label_mode}
          onGroups={setGroups} onRoles={setRoles} onBack={() => setStep("upload")} onApply={apply} onRestart={restart} />
      )}
      {step === "done" && result && (
        <>
          <div className="empty">
            Добавлено <b>{result.photos}</b> фото в <b>{result.folders.length}</b> товаров
            {result.labels > 0 && <>, этикеток (в генерацию не идут): <b>{result.labels}</b></>}.
            {result.merged.length > 0 && <div>Дополнены существующие товары: {result.merged.join(", ")}</div>}
            {opts.auto_profile && <p>Для новых товаров ИИ составляет профиль и промпты — они появятся в списке через несколько секунд.</p>}
          </div>
          <div className="row"><span className="spacer" /><button className="primary" onClick={finish}>Готово</button></div>
        </>
      )}
    </Modal>
  );
}
