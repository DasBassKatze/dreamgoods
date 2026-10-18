// Тонкая обёртка над fetch и все вызовы API в одном месте.
import type {
  AccountBalance,
  AdminOverview,
  FinanceView,
  KeysListing,
  Me,
  UsersListing,
  CatalogModel,
  FrameVersion,
  HistoryItem,
  ImportResult,
  ImportView,
  PersonaListing,
  PersonaStyle,
  PhotoRole,
  Preset,
  PresetApplyResult,
  PresetListing,
  StyleListing,
  ProfileData,
  ProfileResponse,
  ProjectRef,
  PriceList,
  ProjectState,
  TopupRequest,
  ReportSelection,
  ServiceReport,
  Settings,
  PlansAdmin,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

/** Сервер ответил «не вошли» — показать страницу входа. */
const AUTH_EVENT = "dg-auth";
export const onAuthLost = (fn: () => void) => {
  window.addEventListener(AUTH_EVENT, fn);
  return () => window.removeEventListener(AUTH_EVENT, fn);
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const init: RequestInit = { method, headers, credentials: "same-origin" };
  if (body instanceof Blob) {
    init.body = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Нет связи с сервером. Проверьте, что окно консоли DreamGoods открыто.", 0);
  }
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* пустой ответ */
  }
  if (!res.ok) {
    const msg = (data as { error?: string } | null)?.error || `HTTP ${res.status}`;
    if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(AUTH_EVENT));
    throw new ApiError(msg, res.status);
  }
  return data as T;
}

const get = <T>(p: string) => request<T>("GET", p);
const post = <T>(p: string, b: unknown = {}) => request<T>("POST", p, b);
const put = <T>(p: string, b: unknown) => request<T>("PUT", p, b);
const patch = <T>(p: string, b: unknown) => request<T>("PATCH", p, b);

export const assetUrl = (id: string, w = 0) => `/api/assets/${id}${w ? `?w=${w}` : ""}`;
/** Ссылка «скачать оригинал» с понятным именем файла. */
export const downloadUrl = (id: string, name: string) => `/api/assets/${id}?dl=${encodeURIComponent(name)}`;

/** Что произойдёт с кадрами при приведении к пресету перед генерацией. */
export interface PresetSync {
  products: number;
  frames: number;
  reshoot: number;
  need_profile: number;
  queued_profiles: number;
  count: number;
}

export interface Selection {
  product_ids?: number[] | null;
  frame_ids?: number[] | null;
  limit?: number;
  /** пожелания к этому запуску — поверх пресета */
  brief?: string;
  market?: string;
  aspect?: string;
}

/** Методы проекта. */
export function projectApi(id: number) {
  const p = `/api/projects/${id}`;
  return {
    state: () => get<ProjectState>(`${p}/state`),
    saveSettings: (values: Partial<Settings> & Record<string, unknown>) => patch<{ ok: true }>(`${p}/settings`, values),
    settingsDefaults: () => get<{ qc_checklist: string }>(`${p}/settings/defaults`),
    catalog: (kind: "image" | "qc", refresh = false) =>
      get<{ models: CatalogModel[]; error: string }>(`${p}/catalog?kind=${kind}${refresh ? "&refresh=true" : ""}`),

    previewGenerate: (sel: Selection) => post<{ count: number; preset: PresetSync | null }>(`${p}/generate/preview`, sel),
    generate: (sel: Selection) => post<{ added: number; preset: PresetSync | null }>(`${p}/generate`, sel),
    previewCheck: (sel: Selection & { only_unchecked?: boolean }) => post<{ count: number }>(`${p}/check/preview`, sel),
    check: (sel: Selection & { only_unchecked?: boolean }) => post<{ added: number }>(`${p}/check`, sel),
    stop: () => post<{ cancelled: number }>(`${p}/stop`),
    clearErrors: () => post<{ ok: true }>(`${p}/errors/clear`),

    getPrompt: (frameId: number) => get<{ prompt: string }>(`${p}/frames/${frameId}/prompt`),
    setPrompt: (frameId: number, text: string) => put<{ ok: true }>(`${p}/frames/${frameId}/prompt`, { text }),
    editFrame: (frameId: number, instruction: string, sourceId?: number) =>
      post<{ ok: true }>(`${p}/frames/${frameId}/edit`, { instruction, source_id: sourceId ?? null }),
    quick: (frameId: number, action: "upscale" | "remove_bg") => post<{ ok: true }>(`${p}/frames/${frameId}/quick`, { action }),
    runs: (before?: number) => get<{ items: HistoryItem[] }>(`${p}/history${before ? `?before=${before}` : ""}`),
    history: (frameId: number) => get<{ versions: FrameVersion[] }>(`${p}/frames/${frameId}/history`),
    restore: (frameId: number, generationId: number) =>
      post<{ ok: true }>(`${p}/frames/${frameId}/restore`, { generation_id: generationId }),
    review: (frameId: number, verdict: "ok" | "bad", comment: string, regen: boolean) =>
      post<{ ok: true }>(`${p}/frames/${frameId}/review`, { verdict, comment, regen }),

    setRefs: (productId: number, selected: string[]) => put<{ selected: number }>(`${p}/products/${productId}/refs`, { selected }),
    getProfile: (productId: number) => get<ProfileResponse>(`${p}/products/${productId}/profile`),
    saveProfile: (productId: number, profile: ProfileData, build: boolean) =>
      put<{ ok: true; prompts: number }>(`${p}/products/${productId}/profile`, { profile, build }),
    generateProfiles: (productIds: number[] | null, build: boolean) =>
      post<{ added: number }>(`${p}/profiles/generate`, { product_ids: productIds, build }),

    newImport: () => post<{ id: number }>(`${p}/imports`),
    getImport: (sid: number) => get<ImportView>(`${p}/imports/${sid}`),
    uploadImportFile: (sid: number, path: string, file: Blob) =>
      request<{ added: number; total: number }>("POST", `${p}/imports/${sid}/files?path=${encodeURIComponent(path)}`, file),
    analyzeImport: (sid: number, group_mode: string, label_mode: string) =>
      post<{ ok: true }>(`${p}/imports/${sid}/analyze`, { group_mode, label_mode }),
    applyImport: (sid: number, groups: { name: string; photos: [string, PhotoRole][] }[], label_mode: string, auto_profile: boolean) =>
      post<ImportResult>(`${p}/imports/${sid}/apply`, { groups, label_mode, auto_profile }),

    exportUrl: (include: "accepted" | "all" | "picked", ids: { frames?: number[]; products?: number[] } = {}) =>
      `${p}/export?include=${include}` + (ids.frames?.length ? `&frames=${ids.frames.join(",")}` : "")
      + (ids.products?.length ? `&products=${ids.products.join(",")}` : ""),

    presets: () => get<PresetListing>(`${p}/presets`),
    savePreset: (id: number | null, body: Omit<Preset, "id" | "total" | "is_default" | "products">) =>
      id ? put<{ ok: true }>(`${p}/presets/${id}`, body) : post<{ id: number }>(`${p}/presets`, body),
    detectSubcategories: () => post<{ ok: true }>(`${p}/presets/subcategories`),
    archivePreset: (id: number) => request<{ ok: true }>("DELETE", `${p}/presets/${id}`),
    applyPreset: (id: number, body: { product_ids?: number[]; categories?: string[]; everything?: boolean;
      make_default?: boolean; rebuild?: boolean; dry_run?: boolean }) => post<PresetApplyResult>(`${p}/presets/${id}/apply`, body),

    styles: () => get<StyleListing>(`${p}/styles`),
    createStyle: (body: { name?: string; note?: string; blocks?: string[] }) => post<{ id: number }>(`${p}/styles`, body),
    updateStyle: (id: number, body: { name?: string; note?: string; description?: string; blocks?: string[] }) =>
      patch<{ ok: true }>(`${p}/styles/${id}`, body),
    archiveStyle: (id: number) => request<{ ok: true }>("DELETE", `${p}/styles/${id}`),
    uploadStylePhoto: (id: number, file: File) =>
      request<{ ok: true }>("POST", `${p}/styles/${id}/photos?name=${encodeURIComponent(file.name)}`, file),
    deleteStylePhoto: (id: number, photoId: number) => request<{ ok: true }>("DELETE", `${p}/styles/${id}/photos/${photoId}`),
    describeStyle: (id: number) => post<{ ok: true }>(`${p}/styles/${id}/describe`),
    setProjectStyle: (id: number) => put<{ ok: true }>(`${p}/style`, { style_ref_id: id }),
    setProductStyle: (productId: number, id: number | null) => put<{ ok: true }>(`${p}/products/${productId}/style`, { style_ref_id: id }),

    personas: () => get<PersonaListing>(`${p}/personas`),
    createPersona: (body: { name?: string; brief?: string; source: "upload" | "generated" }) => post<{ id: number }>(`${p}/personas`, body),
    updatePersona: (id: number, body: { name?: string; brief?: string; description?: string; style?: PersonaStyle;
      consent?: boolean; groups?: string[] }) =>
      patch<{ ok: true }>(`${p}/personas/${id}`, body),
    archivePersona: (id: number) => request<{ ok: true }>("DELETE", `${p}/personas/${id}`),
    uploadPersonaPhoto: (id: number, file: File) =>
      request<{ ok: true }>("POST", `${p}/personas/${id}/photos?name=${encodeURIComponent(file.name)}`, file),
    uploadPersonaRef: (id: number, file: File) =>
      request<{ ok: true }>("POST", `${p}/personas/${id}/refs?name=${encodeURIComponent(file.name)}`, file),
    deletePersonaPhoto: (id: number, photoId: number) => request<{ ok: true }>("DELETE", `${p}/personas/${id}/photos/${photoId}`),
    describePersona: (id: number) => post<{ ok: true }>(`${p}/personas/${id}/describe`),
    personaCandidates: (id: number, count: number, brief?: string) =>
      post<{ ok: true }>(`${p}/personas/${id}/candidates`, { count, brief }),
    editPersona: (id: number, request: string, count: number) => post<{ ok: true }>(`${p}/personas/${id}/edit`, { request, count }),
    choosePersonaPhoto: (id: number, photoId: number) => post<{ ok: true }>(`${p}/personas/${id}/choose`, { photo_id: photoId }),
    personaSheet: (id: number) => post<{ ok: true }>(`${p}/personas/${id}/sheet`),
    setProjectPersona: (personaId: number) => put<{ ok: true }>(`${p}/persona`, { persona_id: personaId }),
    setProductPersona: (productId: number, personaId: number | null) =>
      put<{ ok: true }>(`${p}/products/${productId}/persona`, { persona_id: personaId }),
  };
}

export type ProjectApi = ReturnType<typeof projectApi>;

export const api = {
  projects: () => get<{ projects: ProjectRef[] }>("/api/projects"),
  createProject: (client: string, name: string) => post<{ id: number }>("/api/projects", { client, name }),
  renameProject: (id: number, name: string) => patch<{ ok: true }>(`/api/projects/${id}`, { name }),
  archiveProject: (id: number) => request<{ ok: true }>("DELETE", `/api/projects/${id}`),
};

export const authApi = {
  me: () => get<Me>("/api/auth/me"),
  login: (email: string, password: string) => post<Me>("/api/auth/login", { email, password }),
  logout: () => post<{ ok: true }>("/api/auth/logout"),
  password: (old: string, next: string) => post<{ ok: true }>("/api/auth/password", { old, new: next }),
  balance: () => get<AccountBalance>("/api/account/balance"),
  storage: () => get<{ used: number; quota: number }>("/api/account/storage"),
  topups: () => get<{ items: TopupRequest[] }>("/api/account/topups"),
  createTopup: (amount: number, method: string, note: string, plan = "", months = 0) =>
    post<TopupRequest>("/api/account/topups", { amount, method, note, plan, months }),
};

const reportQuery = (q: { from: string; to: string; client?: number | null; rate: number }) =>
  `date_from=${q.from}&date_to=${q.to}&usn_rate=${q.rate}${q.client ? `&client_id=${q.client}` : ""}`;

export const publicApi = {
  prices: () => get<PriceList>("/api/public/prices"),
};

export const adminApi = {
  topups: (status = "") => get<{ items: TopupRequest[] }>(`/api/admin/topups${status ? `?status=${status}` : ""}`),
  resolveTopup: (id: number, action: "paid" | "cancel") => post<{ ok: true }>(`/api/admin/topups/${id}/${action}`),
  users: () => get<UsersListing>("/api/admin/users"),
  plans: () => get<PlansAdmin>("/api/admin/plans"),
  savePlans: (plans: Record<string, Record<string, unknown>>) => put<PlansAdmin>("/api/admin/plans", { plans }),
  createUser: (body: Record<string, unknown>) => post<{ id: number }>("/api/admin/users", body),
  updateUser: (id: number, body: Record<string, unknown>) => patch<{ ok: true }>(`/api/admin/users/${id}`, body),
  topup: (clientId: number, amount: number, note: string) =>
    post<{ balance: number }>(`/api/admin/clients/${clientId}/topup`, { amount, note }),
  setMarkup: (markup: number) => put<{ ok: true }>("/api/admin/markup", { markup }),
  keys: (refresh = false) => get<KeysListing>(`/api/admin/keys${refresh ? "?refresh=true" : ""}`),
  createKey: (body: Record<string, unknown>) => post<{ id: number }>("/api/admin/keys", body),
  updateKey: (id: number, body: Record<string, unknown>) => patch<{ ok: true }>(`/api/admin/keys/${id}`, body),
  deleteKey: (id: number) => request<{ ok: true }>("DELETE", `/api/admin/keys/${id}`),
  report: (q: { from: string; to: string; client?: number | null; rate: number }) =>
    get<ServiceReport>(`/api/admin/report?${reportQuery(q)}`),
  reportCsvUrl: (q: { from: string; to: string; client?: number | null; rate: number }, sel?: ReportSelection) =>
    `/api/admin/report?${reportQuery(q)}&format=csv` + (sel ? (["metrics", "sections", "cols"] as const)
      .map((k) => `&${k}=${sel[k].length ? sel[k].join(",") : "none"}`).join("") : ""),
  finance: (clientId?: number) => get<FinanceView>(`/api/admin/finance${clientId ? `?client_id=${clientId}` : ""}`),
  overview: (projectId: number) => get<AdminOverview>(`/api/admin/projects/${projectId}/overview`),
  log: (lines = 400, level = "") => get<{ lines: string[] }>(`/api/admin/log?lines=${lines}&level=${level}`),
  setParallel: (n: number) => put<{ parallel: number }>("/api/admin/parallel", { n }),
  resume: () => post<{ resumed: number }>("/api/admin/resume"),
};
