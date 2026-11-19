import { useEffect, useRef, useState } from "react";
import type { TextileJob } from "../../api/client";
import { useProject } from "../../ProjectContext";
import { cropFabric, FabricSelection, type FabricRegion } from "./FabricSelection";

function working(job: TextileJob | null) {
  return job !== null && ["queued", "running", "cancelling", "paused"].includes(job.status);
}

export function Textile() {
  const { api } = useProject();
  const [photo, setPhoto] = useState<File>();
  const [fabric, setFabric] = useState<File>();
  const [region, setRegion] = useState<FabricRegion | null>(null);
  const [prompt, setPrompt] = useState("");
  const [job, setJob] = useState<TextileJob | null>(null);
  const [resultId, setResultId] = useState<number | null>(null);
  const [brokenImageId, setBrokenImageId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const fabricImage = useRef<HTMLImageElement>(null);
  const busy = working(job);

  useEffect(() => {
    if (sending || stopping) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const { job: next, result_id } = await api.textileJob();
        if (!live) return;
        setJob(next);
        setResultId(result_id);
        if (working(next ?? null)) timer = setTimeout(refresh, 1800);
      } catch {
        if (live) timer = setTimeout(refresh, 3500);
      } finally {
        if (live) setLoading(false);
      }
    };
    void refresh();
    return () => { live = false; clearTimeout(timer); };
  }, [api, sending, stopping]);

  const start = async () => {
    if (!photo || !fabric || submitting.current || busy) return;
    submitting.current = true;
    setSending(true);
    setError("");
    try {
      const swatch = await cropFabric(fabric, region, fabricImage.current);
      setJob(await api.transferTextile(photo, swatch, prompt.trim()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      submitting.current = false;
      setSending(false);
    }
  };

  const cancel = async () => {
    if (!job || stopping) return;
    setStopping(true);
    setError("");
    try {
      setJob(await api.cancelTextile(job.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStopping(false);
    }
  };

  return <>
    <fieldset disabled={sending || busy}>
      <label>Фото одежды<input type="file" accept="image/jpeg,image/png,image/webp"
        onChange={e => setPhoto(e.target.files?.[0])} /></label>
      <label>Образец ткани<input type="file" accept="image/jpeg,image/png,image/webp"
        onChange={e => { setRegion(null); setFabric(e.target.files?.[0]); }} /></label>
      {fabric && <FabricSelection file={fabric} region={region} onChange={setRegion}
        imageRef={fabricImage} disabled={sending || busy} />}
      <label>Дополнительные указания (необязательно)
        <textarea value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={1500}
          placeholder="Например, оставь рукава без изменений" />
      </label>
      <button className="primary" disabled={!photo || !fabric || loading} onClick={() => void start()}>
        Перенести ткань
      </button>
    </fieldset>
    {sending && <p role="status">Загружаю фотографии…</p>}
    {job?.status === "queued" && <p role="status">В очереди</p>}
    {job?.status === "running" && <p role="status">ИИ переносит ткань…</p>}
    {job?.status === "paused" && <p role="alert">Задание приостановлено. Проверьте раздел операций.</p>}
    {busy && job?.status !== "cancelling" && <button type="button" disabled={stopping}
      onClick={() => void cancel()}>Отменить перенос</button>}
    {job?.status === "cancelling" && <p role="status">Отменяю перенос…</p>}
    {job?.status === "cancelled" && <p role="status">Задание остановлено</p>}
    {(error || job?.error) && <p role="alert">{error || job?.error}</p>}
    <section className="textile-result" aria-labelledby="textile-result-title">
      <h2 id="textile-result-title">Результат</h2>
      {resultId == null ? <p className="hint">Здесь появится готовое фото.</p> : <>
        {resultId !== job?.id && <p className="hint">Последний готовый перенос</p>}
        {brokenImageId === resultId ? <p role="alert">Не удалось загрузить предпросмотр.</p> :
          <img key={resultId} className="creative-result" src={api.textileImage(resultId)}
            alt="Результат переноса ткани" onError={() => setBrokenImageId(resultId)} />}
        <a className="btn" href={api.textileImage(resultId, true)} download>Скачать результат</a>
      </>}
    </section>
  </>;
}
