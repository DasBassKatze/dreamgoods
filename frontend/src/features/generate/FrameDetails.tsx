import { useCallback, useEffect, useState } from "react";
import { assetUrl, downloadUrl } from "../../api/client";
import type { FrameVersion } from "../../api/types";
import { useUI } from "../../components/ui";
import { useActions } from "../../hooks/useActions";
import { Icon } from "../../layout/Icon";
import { QC_LABEL, STATE_LABEL, isBusy, pad, qcStatus } from "../../lib/format";
import { useProject } from "../../ProjectContext";

interface Props {
  productId: number;
  frameId: number;
  onOpen: () => void;
  onClose: () => void;
}

const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "");

/** Правая панель «Детали изображения»: выбранный кадр, его параметры, быстрые действия и вариации. */
export function FrameDetails({ productId, frameId, onOpen, onClose }: Props) {
  const { state, api, reload, run, product } = useProject();
  const { regenerate, quick } = useActions();
  const ui = useUI();
  const [versions, setVersions] = useState<FrameVersion[]>([]);
  const [edit, setEdit] = useState("");
  const p = product(productId);
  const f = p?.frames.find((x) => x.id === frameId);

  const load = useCallback(async () => {
    try {
      setVersions((await api.history(frameId)).versions);
    } catch {
      setVersions([]);
    }
  }, [api, frameId]);
  useEffect(() => { setEdit(""); }, [frameId]);
  useEffect(() => { load(); }, [load, f?.generation, f?.state]);

  if (!p || !f) return null;
  const preset = (p.preset_id ? state.presets.find((x) => x.id === p.preset_id) : null) || state.preset;
  const q = qcStatus(f);
  const busy = isBusy(f);
  const status = busy || f.state === "error" ? (STATE_LABEL[f.state] || f.state) + (f.note ? ` · ${f.note}` : "")
    : f.asset ? (q ? QC_LABEL[q] || "готов" : "готов") : "ещё не снят";

  const sendEdit = () =>
    run(async () => {
      const text = edit.trim();
      if (!text) return;
      await api.editFrame(f.id, text);
      setEdit("");
      ui.toast("Правка поставлена в очередь — новая версия появится в «Вариациях»");
      await reload();
    });

  const restore = (v: FrameVersion) =>
    run(async () => {
      if (v.current || v.pending || !v.asset) return;
      if (!(await ui.confirm({ text: "Сделать эту версию текущей для кадра?", ok: "Сделать текущей" }))) return;
      await api.restore(f.id, v.id);
      await reload();
    });

  const shown = versions.filter((v) => v.asset || v.pending);

  return (
    <div className="panel details">
      <div className="det-h">
        <h3>Детали изображения</h3>
        <span className="spacer" />
        <button className="icon-btn ghost" title="Закрыть" onClick={onClose}><Icon name="close" size={16} /></button>
      </div>
      <button className="det-img" onClick={onOpen} title="Открыть кадр целиком" style={{ aspectRatio: (preset?.aspect || "3:4").replace(":", "/") }}>
        {f.asset ? <img src={assetUrl(f.asset, 800)} alt="" /> : <span className="ph">{pad(f.i)}</span>}
        {busy && <span className="det-busy"><i className="dot-run" /> {STATE_LABEL[f.state]}</span>}
      </button>
      <div className="det-title">
        <b>{p.sku} · кадр {pad(f.i)}</b>
        <small>{f.block}</small>
      </div>
      {f.shot && <p className="det-shot">{f.shot}</p>}
      <dl className="det-params">
        <dt>Статус</dt><dd className={f.state === "error" ? "err-text" : q === "review" ? "warn-text" : ""}>{status}</dd>
        <dt>Площадка</dt><dd>{preset?.market_name || "без площадки"}</dd>
        <dt>Формат</dt><dd>{preset?.aspect || "3:4"}</dd>
        <dt>Пресет</dt><dd>{preset?.name || "—"}</dd>
        {f.qc?.defects.length ? <><dt>Замечания</dt><dd className="warn-text">{f.qc.defects.slice(0, 3).join("; ")}</dd></> : null}
        {f.error ? <><dt>Ошибка</dt><dd className="err-text">{f.error}</dd></> : null}
      </dl>

      <div className="det-actions">
        {f.asset ? (
          <a className="btn" href={downloadUrl(f.asset, `${p.sku}_${pad(f.i)}`)}><Icon name="download" size={16} /> Скачать</a>
        ) : <button disabled><Icon name="download" size={16} /> Скачать</button>}
        <button disabled={!f.asset || busy} onClick={() => quick(p, f, "upscale")}><Icon name="upscale" size={16} /> Улучшить до 4K</button>
        <button disabled={!f.asset || busy} onClick={() => quick(p, f, "remove_bg")}><Icon name="eraser" size={16} /> Удалить фон</button>
        <button disabled={busy} onClick={() => regenerate(p, f)}><Icon name="regen" size={16} /> {f.asset ? "Переснять" : "Сгенерировать"}</button>
      </div>

      {f.asset && (
        <div className="det-edit">
          <label className="cmp-label">Редактировать</label>
          <div className="row">
            <input value={edit} maxLength={1000} placeholder="Что изменить? «Сделай фон светлее»"
              onChange={(e) => setEdit(e.target.value)} onKeyDown={(e) => e.key === "Enter" && sendEdit()} disabled={busy} />
            <button className="primary" disabled={!edit.trim() || busy} onClick={sendEdit}>Изменить</button>
          </div>
          <button className="link" onClick={onOpen}><Icon name="expand" size={14} /> открыть редактор и проверку</button>
        </div>
      )}

      {shown.length > 0 && (
        <div className="det-vars">
          <label className="cmp-label">Вариации <small>{shown.length}</small></label>
          <div className="vars">
            {shown.map((v) => (
              <button key={v.id} className={`var ${v.current ? "on" : ""} ${v.pending ? "pending" : ""}`} onClick={() => restore(v)}
                title={(v.current ? "Текущая версия" : "Сделать текущей") + (v.edit ? ` · правка: ${v.edit}` : "") + ` · ${fmtTime(v.created)}`}>
                {v.asset ? <img loading="lazy" src={assetUrl(v.asset, 200)} alt="" /> : <span className="ph">…</span>}
                {v.qc === "fail" && <i className="var-flag" title="ИИ нашёл брак" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
