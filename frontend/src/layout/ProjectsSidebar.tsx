import { useEffect, useState } from "react";
import { assetUrl, authApi } from "../api/client";
import type { ProjectRef } from "../api/types";
import { Icon } from "./Icon";
import { SiteFooter } from "./SiteFooter";

interface Props {
  master: boolean;
  projects: ProjectRef[];
  projectId: number | null;
  onProject: (id: number) => void;
  onNewProject: () => void;
  open: boolean;
  onClose: () => void;
}

const gb = (b: number) => (b / 1024 ** 3 >= 10 ? Math.round(b / 1024 ** 3) : Math.round((b / 1024 ** 3) * 10) / 10)
  .toLocaleString("ru-RU");

/** Слева: проекты с картинками (мастеру — по кабинетам), внизу — занятое место в хранилище. */
export function ProjectsSidebar(p: Props) {
  const [storage, setStorage] = useState<{ used: number; quota: number } | null>(null);
  useEffect(() => {
    authApi.storage().then(setStorage).catch(() => {});
    const t = window.setInterval(() => authApi.storage().then(setStorage).catch(() => {}), 120000);
    return () => window.clearInterval(t);
  }, []);
  const groups = new Map<string, ProjectRef[]>();
  for (const pr of p.projects) groups.set(pr.client, [...(groups.get(pr.client) || []), pr]);
  const pct = storage ? Math.min(100, (storage.used / Math.max(1, storage.quota)) * 100) : 0;

  const row = (pr: ProjectRef) => (
    <button key={pr.id} className={`proj-item ${pr.id === p.projectId ? "on" : ""}`} onClick={() => { p.onProject(pr.id); p.onClose(); }}>
      <span className="proj-thumb">{pr.thumb ? <img src={assetUrl(pr.thumb, 96)} alt="" loading="lazy" /> : <Icon name="folder" size={18} />}</span>
      <span className="proj-text"><b>{pr.name}</b><small>{pr.products ? `${pr.products} товар.` : "пусто"}</small></span>
    </button>
  );

  return (
    <>
      {p.open && <div className="scrim" onClick={p.onClose} />}
      <aside className={`projects-side ${p.open ? "open" : ""}`}>
        <div className="ps-head">
          <h2>Мои проекты</h2>
          <button className="icon-btn" title="Новый проект" aria-label="Новый проект" onClick={p.onNewProject}><Icon name="plus" size={16} /></button>
        </div>
        <div className="ps-list">
          {!p.projects.length && <div className="hint">Проектов пока нет</div>}
          {p.master && groups.size > 1
            ? [...groups.entries()].map(([client, list]) => (
                <div key={client} className="ps-group"><div className="ps-client">{client}</div>{list.map(row)}</div>
              ))
            : p.projects.map(row)}
        </div>
        {storage && (
          <div className="storage">
            <div className="storage-text">Использовано {gb(storage.used)} ГБ из {gb(storage.quota)} ГБ</div>
            <div className={`storage-bar ${pct > 90 ? "full" : ""}`}><i style={{ width: `${Math.max(pct, 1.5)}%` }} /></div>
          </div>
        )}
        <SiteFooter />
      </aside>
    </>
  );
}
