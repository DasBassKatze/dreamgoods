import { useEffect, useRef, useState } from "react";
import type { TextileJob } from "../../api/client";
import { useProject } from "../../ProjectContext";

function working(job: TextileJob | null) {
  return job !== null && ["queued", "running", "cancelling", "paused"].includes(job.status);
}

export function Textile() {
  const { api } = useProject();
  const [photo, setPhoto] = useState<File>();
  const [fabric, setFabric] = useState<File>();
  const [job, setJob] = useState<TextileJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const busy = working(job);

  useEffect(() => {
    if (sending) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const { job: next } = await api.textileJob();
        if (!live) return;
        setJob(next);
        if (working(next ?? null)) timer = setTimeout(refresh, 1800);
      } catch {
        if (live) timer = setTimeout(refresh, 3500);
      } finally {
        if (live) setLoading(false);
      }
    };
    void refresh();
    return () => { live = false; clearTimeout(timer); };
  }, [api, sending]);

  const start = async () => {
    if (!photo || !fabric || submitting.current || busy) return;
    submitting.current = true;
    setSending(true);
    setError("");
    try {
      setJob(await api.transferTextile(photo, fabric));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      submitting.current = false;
      setSending(false);
    }
  };

  return <>
    <fieldset disabled={sending || busy}>
      <label>Фото одежды<input type="file" accept="image/jpeg,image/png,image/webp"
        onChange={e => setPhoto(e.target.files?.[0])} /></label>
      <label>Образец ткани<input type="file" accept="image/jpeg,image/png,image/webp"
        onChange={e => setFabric(e.target.files?.[0])} /></label>
      <p className="hint">Загрузите один образец ткани, который нужно перенести на одежду.</p>
      <button className="primary" disabled={!photo || !fabric || loading} onClick={() => void start()}>
        Перенести ткань
      </button>
    </fieldset>
    {sending && <p role="status">Загружаю фотографии…</p>}
    {job?.status === "queued" && <p role="status">В очереди</p>}
    {job?.status === "running" && <p role="status">ИИ переносит ткань…</p>}
    {job?.status === "paused" && <p role="alert">Задание приостановлено. Проверьте раздел операций.</p>}
    {job?.status === "cancelled" && <p role="status">Задание остановлено</p>}
    {(error || job?.error) && <p role="alert">{error || job?.error}</p>}
    {job?.has_image && <div>
      <img className="creative-result" src={api.textileImage(job.id)} alt="Результат переноса ткани" />
      <a className="btn" href={api.textileImage(job.id, true)} download>Скачать результат</a>
    </div>}
  </>;
}
