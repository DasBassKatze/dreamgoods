import { useCallback, useEffect, useRef, useState } from "react";
import { assetUrl } from "../../api/client";
import type { FrameVersion, Product, ProjectState } from "../../api/types";
import { Modal } from "../../components/Modal";
import { matchesFilter } from "../../components/ProductList";
import type { Filter } from "../../components/Toolbar";
import { useUI } from "../../components/ui";
import { useActions } from "../../hooks/useActions";
import { STATE_LABEL, isBusy, pad, qcStatus, rub } from "../../lib/format";
import { useProject } from "../../ProjectContext";
import { CompareImages } from "./CompareImages";
import { QcSummary } from "./QcSummary";

interface Props {
  productId: number;
  frameId: number;
  filter: Filter;
  onNavigate: (productId: number, frameId: number) => void;
  onClose: () => void;
}

type ReviewKind = "ok" | "bad" | "badregen" | "check";

const QUICK = ["Сделай фон светлее и чище", "Убери лишние предметы", "Товар крупнее в кадре", "Убери тень под товаром",
  "Сделай свет мягче", "Поверни товар носком к камере"];

export function FrameViewer({ productId, frameId, filter, onNavigate, onClose }: Props) {
  const { state, api, reload, run, product } = useProject();
  const { regenerate } = useActions();
  const ui = useUI();
  const [comment, setComment] = useState("");
  const [edit, setEdit] = useState("");
  const [versions, setVersions] = useState<FrameVersion[]>([]);
  const [view, setView] = useState<number | null>(null);   // какую версию смотрим (null — текущую)

  const p = product(productId);
  const f = p?.frames.find((x) => x.id === frameId);

  const loadHistory = useCallback(async () => {
    try {
      setVersions((await api.history(frameId)).versions);
    } catch {
      setVersions([]);
    }
  }, [api, frameId]);

  useEffect(() => {
    setComment("");
    setEdit("");
    setView(null);
  }, [frameId]);
  // история обновляется, когда у кадра меняется картинка или состояние
  useEffect(() => {
    loadHistory();
  }, [loadHistory, f?.generation, f?.state]);

  const step = (d: number) => {
    if (!p) return;
    const n = p.frames.findIndex((x) => x.id === frameId);
    const next = p.frames[(n + d + p.frames.length) % p.frames.length];
    if (next) onNavigate(p.id, next.id);
  };

  /** После решения — к следующему кадру этого товара, затем к следующему товару (удобно размечать подряд). */
  const nextToReview = (s: ProjectState) => {
    const want = (fr: Product["frames"][number]) => !!fr.asset && (filter !== "review" || qcStatus(fr) === "review");
    const products = s.products.filter((x) => matchesFilter(x, filter) || x.id === productId);
    const k = products.findIndex((x) => x.id === productId);
    const cur = products[k];
    const pos = cur?.frames.findIndex((x) => x.id === frameId) ?? -1;
    const here = cur?.frames.slice(pos + 1).find(want);
    if (here) return onNavigate(cur.id, here.id);
    for (const other of products.slice(k + 1)) {
      const fr = other.frames.find(want);
      if (fr) {
        ui.toast(`Переход к следующему товару: ${other.sku}`);
        return onNavigate(other.id, fr.id);
      }
    }
    ui.toast("Это был последний кадр — размечать больше нечего");
    onClose();
  };

  const review = (kind: ReviewKind) =>
    run(async () => {
      if (!f || !f.asset || isBusy(f) || view != null) return;
      if (kind === "check") {
        await api.check({ frame_ids: [f.id] });
        ui.toast("Кадр отправлен на проверку");
        await reload();
        return;
      }
      await api.review(f.id, kind === "ok" ? "ok" : "bad", comment.trim(), kind === "badregen");
      ui.toast(kind === "ok" ? "Принято" : kind === "bad" ? "Отмечен как брак" : "Брак, кадр поставлен на перегенерацию");
      const s = await reload();
      if (s) nextToReview(s);
    });

  const shown = view != null ? versions.find((v) => v.id === view) : undefined;
  const sourceId = shown && !shown.current ? shown.id : undefined;

  const submitEdit = () =>
    run(async () => {
      const text = edit.trim();
      if (!text || !f) return;
      await api.editFrame(f.id, text, sourceId);
      ui.toast("Правка поставлена в очередь — новая версия появится через минуту");
      setEdit("");
      setView(null);
      await reload();
    });

  const restore = (v: FrameVersion) =>
    run(async () => {
      if (!f) return;
      await api.restore(f.id, v.id);
      ui.toast("Эта версия теперь основная");
      setView(null);
      await reload();
      await loadHistory();
    });

  // горячие клавиши: 1 — принять, 2 — брак, 3 — брак и переделать, ← → — листать
  const keys = useRef<(e: KeyboardEvent) => void>(() => {});
  keys.current = (e) => {
    const t = e.target as HTMLElement;
    if (t.tagName === "TEXTAREA" || t.tagName === "INPUT") return;
    if (document.querySelectorAll(".modal").length > 1) return; // поверх открыт диалог
    if (e.key === "1") review("ok");
    else if (e.key === "2") review("bad");
    else if (e.key === "3") review("badregen");
    else if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
  };
  useEffect(() => {
    const h = (e: KeyboardEvent) => keys.current(e);
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, []);

  if (!p || !f) {
    return (
      <Modal title="Кадр" onClose={onClose}>
        <div className="empty">Кадр не найден (возможно, промпты товара пересобраны)</div>
      </Modal>
    );
  }

  const busy = isBusy(f);
  const label = STATE_LABEL[f.state];
  const img = shown?.asset || f.asset;
  const ready = versions.filter((v) => v.asset || v.pending);
  return (
    <Modal title={<>{p.sku} · кадр {pad(f.i)} · {f.block}{label ? <span className="hint"> · {f.note || label}</span> : null}</>}
      width={1240} onClose={onClose}
      actions={<><button onClick={() => step(-1)} title="Предыдущий (←)">←</button><button onClick={() => step(1)} title="Следующий (→)">→</button></>}>
      <div className="lb">
        <div className="lb-left">
          <div className={`img ${busy ? "busy" : ""}`}>
            {img ? <img src={assetUrl(img, 1400)} alt="" /> : <div className="empty">Кадр ещё не сгенерирован</div>}
            {busy && <div className="img-busy"><span className="spinner" />{f.note || label}</div>}
          </div>
          <details><summary>Сравнить с исходным фото товара</summary>
            <CompareImages left={p.photos.find((x) => x.selected)?.asset} right={img} />
          </details>
          {shown && !shown.current && (
            <div className="version-banner">
              Вы смотрите {shown.edit ? "правку" : "вариант"} от {fmtTime(shown.created)}{shown.edit && <> — «{shown.edit}»</>}
              <span className="spacer" />
              <button onClick={() => setView(null)}>К текущей</button>
              <button className="primary" disabled={busy} onClick={() => restore(shown)}>Сделать основной</button>
            </div>
          )}
          {ready.length > 1 && (
            <div className="versions">
              <span className="hint">Версии ({ready.length}):</span>
              {ready.map((v) => (
                <button key={v.id} className={`ver ${(view ?? versions.find((x) => x.current)?.id) === v.id ? "on" : ""}`}
                  disabled={v.pending} onClick={() => setView(v.current ? null : v.id)}
                  title={(v.edit ? `Правка: ${v.edit}` : "Генерация") + (v.cost != null ? ` · ${rub(v.cost)} · ${v.model}` : "")}>
                  {v.asset ? <img src={assetUrl(v.asset, 160)} alt="" /> : <span className="spinner" />}
                  {v.current && <i className="vt cur">основная</i>}
                  {!v.current && v.edit && <i className="vt">✏</i>}
                  {v.qc && <i className={`vq ${v.qc}`}>{v.qc === "pass" ? "✓" : "✗"}</i>}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="lb-right">
          <QcSummary frame={f} />
          {f.error && <div className="err-text">{f.error}</div>}

          {f.asset && (
            <section className="lb-sec">
              <h4>Оценка текущей версии</h4>{sourceId && <p className="hint">Сначала вернитесь к текущей версии или сделайте выбранную основной.</p>}
              <input type="text" className="w-full" placeholder="замечание к браку: что не так (необязательно)"
                value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="row review-buttons">
                <button className="ok" disabled={busy || sourceId != null} onClick={() => review("ok")}>✓ Принять <span className="kbd">1</span></button>
                <button className="bad" disabled={busy || sourceId != null} onClick={() => review("bad")}>✗ Брак <span className="kbd">2</span></button>
                <button className="bad" disabled={busy || sourceId != null} onClick={() => review("badregen")}>✗ Брак и переделать <span className="kbd">3</span></button>
                <button disabled={busy || sourceId != null} onClick={() => review("check")} title="ИИ-проверка этой картинки">🔍</button>
              </div>
            </section>
          )}

          {f.asset ? (
            <section className="lb-sec edit-sec">
              <h4>✏️ Правка фото</h4>
              <div className="hint">Опишите своими словами, что изменить{sourceId ? " в выбранной версии" : ""}. Остальное — композиция,
                свет, модель и сам товар — останется как есть. Старая версия сохранится в истории.</div>
              <textarea className="edit-input" rows={3} value={edit} placeholder="Например: убери складку на заднике и сделай фон чуть теплее"
                onChange={(e) => setEdit(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submitEdit(); }} />
              <div className="quick">
                {QUICK.map((q) => <button key={q} className="qchip" onClick={() => setEdit((cur) => (cur.trim() ? `${cur.trim()}; ${q.toLowerCase()}` : q))}>{q}</button>)}
              </div>
              <div className="row">
                <button className="primary" disabled={busy || edit.trim().length < 3} onClick={submitEdit}>✏️ Изменить фото</button>
                <span className="hint">Ctrl+Enter</span>
              </div>
            </section>
          ) : null}

          <section className="lb-sec">
            <div className="row">
              <button className={f.asset ? "" : "primary"} disabled={f.state === "queued" || f.state === "running"}
                onClick={() => regenerate(p, f)}>
                {f.asset ? "↻ Сгенерировать заново" : "▶ Сгенерировать"}
              </button>
              <button disabled={!img} onClick={() => img && window.open(assetUrl(img), "_blank")}>Открыть оригинал</button>
            </div>
            <div className="hint mt8">Клавиши: 1 — принять, 2 — брак, 3 — брак и переделать, ← → — листать, Esc — закрыть.</div>
            {!state.settings.qc_enabled && <div className="hint">ИИ-проверка выключена.</div>}
          </section>

          {state.admin && <AdminPrompt frameId={f.id} />}
        </div>
      </div>
    </Modal>
  );
}

function fmtTime(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Промпт кадра — только для администратора (свернут). */
function AdminPrompt({ frameId }: { frameId: number }) {
  const { api, run } = useProject();
  const ui = useUI();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    setText(null);
    setOpen(false);
  }, [frameId]);
  useEffect(() => {
    if (open && text == null) api.getPrompt(frameId).then((r) => setText(r.prompt)).catch((e) => ui.toast(e.message));
  }, [open, text, api, frameId, ui]);
  return (
    <details className="lb-sec admin-only" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>🛠 Промпт кадра (админ)</summary>
      {text == null ? <div className="hint">Загрузка…</div> : (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button onClick={() => run(async () => { await api.setPrompt(frameId, text); ui.toast("Промпт кадра сохранён"); })}>Сохранить промпт</button>
          </div>
        </>
      )}
    </details>
  );
}

