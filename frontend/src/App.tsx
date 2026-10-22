import { useCallback, useEffect, useMemo, useState } from "react";
import { api, authApi, onAuthLost, projectApi } from "./api/client";
import type { Me, ProjectRef } from "./api/types";
import { PageMode } from "./components/Modal";
import type { Filter } from "./components/Toolbar";
import { useUI } from "./components/ui";
import { AccountPage } from "./features/account/AccountPage";
import { BalancePage } from "./features/account/BalancePage";
import { AdminPanel } from "./features/admin/AdminPanel";
import { LoginPage } from "./features/auth/LoginPage";
import { ModelCatalog, type CatalogKind, type CatalogPick } from "./features/catalog/ModelCatalog";
import { FrameViewer } from "./features/frame/FrameViewer";
import { GalleryPage } from "./features/gallery/GalleryPage";
import { GenerationPage } from "./features/generate/GenerationPage";
import { HistoryPage } from "./features/history/HistoryPage";
import { ImportWizard } from "./features/import/ImportWizard";
import { FinancePage } from "./features/master/FinancePage";
import { ReportsPage } from "./features/master/ReportsPage";
import { KeysPage } from "./features/master/KeysPage";
import { UsersPage } from "./features/master/UsersPage";
import { PersonaManager } from "./features/personas/PersonaManager";
import { PresetManager } from "./features/presets/PresetManager";
import { ProfileEditor } from "./features/profile/ProfileEditor";
import { SettingsDialog } from "./features/settings/SettingsDialog";
import { StyleManager } from "./features/styles/StyleManager";
import { usePersistentState } from "./hooks/usePersistentState";
import { useProjectState } from "./hooks/useProjectState";
import { useReadyNotify } from "./lib/notify";
import { useRoute, type Route } from "./hooks/useRoute";
import { ProjectsSidebar } from "./layout/ProjectsSidebar";
import { ANALYTICS_ROUTES, AnalyticsNav, SECTION_ROUTES, SectionNav } from "./layout/SectionNav";
import { TopBar } from "./layout/TopBar";
import { ProjectCtx, type ProjectScope } from "./ProjectContext";

export interface Dialogs {
  openFrame: (productId: number, frameId: number) => void;
  openProfile: (productId: number) => void;
  openSettings: () => void;
  openCatalog: (kind: CatalogKind) => void;
  openImport: () => void;
  openPersonas: () => void;
  openPresets: () => void;
  openStyles: () => void;
  openAdmin: () => void;
}

/** Вход на сайт: без учётной записи — страница входа, иначе кабинет. */
export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    authApi.me().then(setMe).catch(() => setMe(null));
    return onAuthLost(() => setMe(null));
  }, []);
  if (me === undefined) return <div className="empty">Загрузка…</div>;
  if (!me) return <LoginPage onLogin={setMe} />;
  return <Workspace key={me.id} me={me} onLogout={async () => { await authApi.logout().catch(() => {}); setMe(null); }} />;
}

const NEEDS_PROJECT: Route[] = ["products", "gallery", "history", "import", "presets", "personas", "styles", "m-analytics", "m-log", "m-settings"];

function Workspace({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const ui = useUI();
  const master = me.role === "master";
  const [route, go] = useRoute();
  const [menuOpen, setMenuOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [projectId, setProjectId] = usePersistentState<number | null>(`project_${me.id}`, null);
  const { state, offline, reload } = useProjectState(projectId);
  useReadyNotify(state, ui.toast);
  const [selectedByProject, setSelectedByProject] = usePersistentState<Record<string, number[]>>("selected", {});
  const [pickedByProject, setPickedByProject] = usePersistentState<Record<string, number[]>>("picked-frames", {});
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(0);

  const [viewer, setViewer] = useState<{ productId: number; frameId: number } | null>(null);
  const [profileOf, setProfileOf] = useState<number | null>(null);
  const [catalog, setCatalog] = useState<CatalogKind | null>(null);
  const [picked, setPicked] = useState<CatalogPick | null>(null);

  useEffect(() => { window.scrollTo(0, 0); }, [route]);
  // чужие разделы не открываются по ссылке
  useEffect(() => {
    if (!master && route.startsWith("m-")) go("products");
  }, [master, route, go]);

  const loadProjects = useCallback(async () => {
    try {
      const r = await api.projects();
      setProjects(r.projects);
      setProjectId((cur) => (cur != null && r.projects.some((p) => p.id === cur) ? cur : r.projects[0]?.id ?? null));
    } catch (e) {
      ui.toast((e as Error).message);
    }
  }, [setProjectId, ui]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);
  // картинки проектов в списке слева обновляются, когда появляются новые готовые кадры
  const doneNow = state?.totals.done;
  useEffect(() => {
    if (doneNow != null) loadProjects();
  }, [doneNow]); // eslint-disable-line react-hooks/exhaustive-deps

  const papi = useMemo(() => (projectId == null ? null : projectApi(projectId)), [projectId]);

  const scope: ProjectScope | null = useMemo(() => {
    if (!state || projectId == null || !papi || state.project.id !== projectId) return null;
    const selected = new Set(selectedByProject[projectId] || []);
    const save = (ids: number[]) => setSelectedByProject((all) => ({ ...all, [projectId]: ids }));
    // выделенные кадры: только те, что ещё есть в проекте (кадр могли удалить или пересобрать)
    const frameIds = new Set(state.products.flatMap((p) => p.frames.map((f) => f.id)));
    const pickedFrames = new Set((pickedByProject[projectId] || []).filter((id) => frameIds.has(id)));
    const savePicked = (ids: number[]) => setPickedByProject((all) => ({ ...all, [projectId]: ids }));
    return {
      state,
      api: papi,
      reload,
      selected,
      toggleSelected: (id, on) => {
        const next = new Set(selected);
        if (on) next.add(id);
        else next.delete(id);
        save([...next]);
      },
      setSelected: save,
      pickedFrames,
      // через функцию обновления: плитки кадров запоминают обработчик, он не должен опираться на старый выбор
      togglePicked: (id, on) => setPickedByProject((all) => {
        const next = new Set(all[projectId] || []);
        if (on) next.add(id);
        else next.delete(id);
        return { ...all, [projectId]: [...next] };
      }),
      setPicked: savePicked,
      product: (id) => state.products.find((p) => p.id === id),
      limit,
      setLimit,
      run: async (fn) => {
        try {
          await fn();
        } catch (e) {
          ui.toast((e as Error).message, 6000);
        }
      },
    };
  }, [state, projectId, papi, selectedByProject, setSelectedByProject, pickedByProject, setPickedByProject, reload, ui, limit]);

  const dialogs: Dialogs = {
    openFrame: (productId, frameId) => setViewer({ productId, frameId }),
    openProfile: setProfileOf,
    openSettings: () => go("m-settings"),
    openCatalog: setCatalog,
    openImport: () => go("import"),
    openPersonas: () => go("personas"),
    openPresets: () => go("presets"),
    openStyles: () => go("styles"),
    openAdmin: () => go("m-analytics"),
  };

  const createProject = async () => {
    const fields = master
      ? [{ key: "name", label: "Название проекта", value: "" },
         { key: "client", label: "Кабинет пользователя (пусто — ваш собственный)", value: "" }]
      : [{ key: "name", label: "Название проекта", value: "" }];
    const v = await ui.ask({ title: "Новый проект", ok: "Создать", fields });
    if (!v) return;
    try {
      const r = await api.createProject(v.client || "", v.name);
      await loadProjects();
      setProjectId(r.id);
      go("products");
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  const toProducts = () => go("products");
  const account = state?.account ?? (me.client ? { balance: me.client.balance, billing: me.client.billing } : null);

  const page = (() => {
    if (!master && route.startsWith("m-")) return null;
    switch (route) {
      case "m-users": return <UsersPage />;
      case "m-keys": return <KeysPage />;
      case "m-finance": return <FinancePage />;
      case "m-reports": return <ReportsPage />;
      case "balance": return <BalancePage />;
      case "account": return <AccountPage me={me} onLogout={onLogout} />;
    }
    if (!scope) {
      return <div className="empty">{projectId == null && projects.length === 0 ? "Проектов пока нет — создайте первый в меню слева."
        : offline ? "Нет связи с сервером. Проверьте, что DreamGoods запущен." : "Загрузка…"}</div>;
    }
    switch (route) {
      case "import": return <PageMode.Provider value><ImportWizard key={projectId} open onClose={toProducts} /></PageMode.Provider>;
      case "presets": return <PageMode.Provider value><PresetManager onClose={toProducts} /></PageMode.Provider>;
      case "personas": return <PageMode.Provider value><PersonaManager onClose={toProducts} /></PageMode.Provider>;
      case "styles": return <PageMode.Provider value><StyleManager onClose={toProducts} /></PageMode.Provider>;
      case "m-settings": return <PageMode.Provider value><SettingsDialog onClose={toProducts} onPickModel={setCatalog} picked={picked} /></PageMode.Provider>;
      case "m-analytics": return <AdminPanel onCatalog={() => setCatalog("image")} />;
      case "m-log": return <AdminPanel onCatalog={() => setCatalog("image")} logOnly />;
      case "gallery": return <GalleryPage dialogs={dialogs} />;
      case "history": return <HistoryPage dialogs={dialogs} onBalance={() => go(master ? "m-finance" : "balance")} />;
      default:
        return <GenerationPage key={projectId} dialogs={dialogs} filter={filter} onFilter={setFilter} onProjectsChanged={loadProjects} />;
    }
  })();

  const body = (
    <div className="app">
      <TopBar me={me} route={route} go={go} balance={account}
        polza={master && state ? { value: state.balance, error: state.balance_error } : null}
        reviewCount={state?.totals.review ?? 0} busy={!!state?.runner.busy} onLogout={onLogout}
        onMenu={() => setMenuOpen((x) => !x)} />
      <div className="app-body">
        <ProjectsSidebar master={master} projects={projects} projectId={projectId}
          onProject={(id) => { setProjectId(id); if (!NEEDS_PROJECT.includes(route)) go("products"); }}
          onNewProject={createProject} open={menuOpen} onClose={() => setMenuOpen(false)} />
        <main className={`content ${NEEDS_PROJECT.includes(route) ? "" : "plain"}`}>
          {offline && scope && <div className="offline">Нет связи с сервером — показаны последние данные.</div>}
          {scope && SECTION_ROUTES.includes(route) && <SectionNav route={route} go={go} />}
          {master && ANALYTICS_ROUTES.includes(route) && <AnalyticsNav route={route} go={go} />}
          {page}
        </main>
      </div>
    </div>
  );

  if (!scope) return body;
  return (
    <ProjectCtx.Provider value={scope}>
      {body}
      {viewer && (
        <FrameViewer productId={viewer.productId} frameId={viewer.frameId} filter={filter}
          onNavigate={(productId, frameId) => setViewer({ productId, frameId })} onClose={() => setViewer(null)} />
      )}
      {profileOf != null && <ProfileEditor productId={profileOf} onClose={() => setProfileOf(null)} />}
      {catalog && master && <ModelCatalog kind={catalog} onClose={() => setCatalog(null)} onPicked={setPicked} />}
    </ProjectCtx.Provider>
  );
}
