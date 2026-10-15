import { useCallback, useEffect, useRef, useState } from "react";
import type { Persona, PersonaListing } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";
import { NewPersona } from "./NewPersona";
import { PersonaCard } from "./PersonaCard";

/** Модели клиента: люди, которые «носят» товары на кадрах. Общие для всех проектов клиента. */
export function PersonaManager({ onClose }: { onClose: () => void }) {
  const { api, state, reload } = useProject();
  const ui = useUI();
  const [list, setList] = useState<Persona[] | null>(null);
  const [meta, setMeta] = useState<Pick<PersonaListing, "groups" | "conflicts">>({ groups: [], conflicts: {} });
  const [creating, setCreating] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const r = await api.personas();
      setList(r.personas);
      setMeta({ groups: r.groups, conflicts: r.conflicts });
      return r.personas;
    } catch (e) {
      ui.toast((e as Error).message);
      return null;
    }
  }, [api, ui]);

  // пока идут задания по моделям — обновляем каждые 2 с
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const l = await load();
      if (!alive) return;
      const busy = l?.some((p) => p.job?.state === "running");
      timer.current = window.setTimeout(tick, busy ? 2000 : 8000);
    };
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer.current);
    };
  }, [load]);

  const refresh = async () => {
    await load();
    await reload();
  };

  return (
    <Modal title={<>Модели клиента <span className="hint">· {state.project.client}</span></>} width={1100} onClose={onClose}
      actions={!creating && <button className="primary" onClick={() => setCreating(true)}>＋ Новая модель</button>}>
      <div className="hint mb10">
        Модель — человек, который «носит» товар на кадрах в использовании и на общих планах. С ней все кадры получаются
        с одним и тем же лицом и фигурой. Кадры на белом фоне делаются без модели. Модели общие для всех проектов клиента.
      </div>
      {creating && (
        <NewPersona onCancel={() => setCreating(false)} onCreated={async () => { setCreating(false); await refresh(); }} />
      )}
      {list == null ? (
        <div className="empty">Загрузка…</div>
      ) : !list.length && !creating ? (
        <div className="empty">
          Моделей пока нет. Загрузите фото своей модели или сгенерируйте образ по описанию.
          <div className="row center"><button className="primary" onClick={() => setCreating(true)}>＋ Новая модель</button></div>
        </div>
      ) : (
        list.map((p) => <PersonaCard key={p.id} persona={p} onChange={refresh} groups={meta.groups} conflicts={meta.conflicts} />)
      )}
    </Modal>
  );
}
