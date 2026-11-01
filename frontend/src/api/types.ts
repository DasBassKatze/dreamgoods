// Типы ответов API (зеркало dreamgoods/services/*.py).

export interface ProjectRef {
  id: number;
  name: string;
  client: string;
  client_id?: number;
}

export type FrameState = "missing" | "queued" | "running" | "checking" | "error" | "done";
export type QcStatus = "unchecked" | "pass" | "review" | "accepted" | "rejected";

export interface QcCounts {
  people?: [number | null, number | null];
  entities?: { name: string; got: number | null; expected: number | null }[];
  body?: Record<string, number | null>[];
}

export interface FrameQc {
  status: QcStatus;
  defects: string[];
  counts: QcCounts | null;
  attempts: number;
  cost: number | null;
  model: string | null;
}

export interface Frame {
  id: number;
  i: number;
  block: string;
  shot: string;
  state: FrameState;
  note: string;
  error: string;
  generation: number | null;
  asset: string | null;
  qc: FrameQc | null;
}

export interface Photo {
  asset: string;
  selected: boolean;
  role: string;
  view: string;
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  persona_id: number | null;
  persona: { id: number; name: string; via: string } | null;
  preset_id: number | null;
  style_ref_id: number | null;
  photos: Photo[];
  frames: Frame[];
  done: number;
  total: number;
  profile: { category: string | null; subcategory: string; summary: string | null; version: number } | null;
  profile_job: { state: "running" | "error"; error?: string } | null;
}

export interface Settings {
  model: string;
  providers: string;
  fallback: boolean;
  aspect: string;
  resolution: string;
  max_refs: number;
  ref_side: number;
  upload_refs: boolean;
  qc_enabled: boolean;
  qc_autoregen: boolean;
  qc_retries: number;
  qc_model: string;
  qc_base_url: string;
  qc_reasoning: string;
  qc_count: boolean;
  qc_count_model: string;
  qc_count_reasoning: string;
  qc_cascade: boolean;
  qc_min_side: number;
  qc_image_side: number;
  qc_checklist: string;
  qc_strictness: string;
  profile_model: string;
  plan_a: number;
  plan_b: number;
  plan_c: number;
  persona_id: number;
  persona_refs: number;
  has_key: boolean;
  has_qc_key: boolean;
}

export interface LogLine {
  t: string;
  kind: "info" | "ok" | "err";
  text: string;
}

export interface Metrics {
  qc_per_frame: number | null;
  qc_passes: { what: string; calls: number; avg: number }[];
  checked: number;
  generated: number;
  first_pass: number | null;
  review: number;
  review_share: number | null;
  accepted: number;
  cost_per_accepted: number | null;
  by_model: { model: string; n: number; first_pass: number | null }[];
  labeled: number;
  caught: number | null;
  missed: number;
  false_rej: number;
  false_rej_pct: number | null;
}

export interface ProjectState {
  pagination: { page: number; page_size: number; total: number; catalog_total: number; todo_products: number; no_prompts: number };
  /** true — мастер-аккаунт (видны себестоимость, баланс Polza, метрики) */
  admin: boolean;
  account: { balance: number; billing: boolean };
  project: ProjectRef;
  persona: { id: number; name: string; asset: string | null } | null;
  style_ref: { id: number; name: string; asset: string | null } | null;
  preset: PresetRef | null;
  presets: PresetRef[];
  settings: Settings;
  warnings: string[];
  products: Product[];
  runner: {
    queued: number;
    running: number;
    busy: boolean;
    ok: number;
    fail: number;
    errors: number;
    spent: number | null;
    stopping: boolean;
  };
  log: LogLine[];
  totals: { done: number; total: number; review: number; spent_all: number | null; avg_cost: number | null };
  metrics: Metrics | null;
  balance: number | null;
  balance_error: string;
}

export interface CatalogModel {
  id: string;
  name: string;
  price: string;
  refs?: boolean;
  providers: { name: string; price?: string }[];
}

export interface ProfileData {
  category?: string;
  category_ru?: string;
  is_pair?: boolean;
  refs?: string[];
  [key: string]: unknown;
}

export interface ProfileResponse {
  sku: string;
  profile: ProfileData | null;
  meta: { model: string; created_at: string; version: number; source: string } | null;
  prompts: number;
  categories: { key: string; name: string }[];
}

export type PhotoRole = "product" | "packaging" | "label" | "junk";

export interface ImportPhoto {
  id: number;
  name: string;
  asset: string;
  role: PhotoRole;
  product?: string;
  article?: string;
  text?: string;
}

export interface ImportGroup {
  id: string;
  name: string;
  article: string;
  articles: string[];
  text: string;
  product: string;
  photos: string[];
  exists: boolean;
  junk?: boolean;
}

export interface ImportView {
  id: number;
  status: "new" | "uploading" | "analyzing" | "ready" | "applying" | "done" | "error";
  progress: [number, number] | null;
  error: string;
  photos: ImportPhoto[];
  groups: ImportGroup[];
  cost: number;
  count: number;
  result: Record<string, unknown>;
}

export interface ImportResult {
  folders: string[];
  photos: number;
  labels: number;
  merged: string[];
}

export type PersonaPhotoKind = "main" | "photo" | "sheet" | "candidate";

export interface PersonaPhoto {
  id: number;
  asset: string;
  kind: PersonaPhotoKind;
  view: string;
  cost: number;
  title: string;
}

export type PersonaStyle = Partial<Record<"makeup" | "hair_styling" | "clothing_style" | "accessories" | "vibe" | "expression", string>>;

export interface Persona {
  id: number;
  name: string;
  brief: string;
  description: string;
  style: PersonaStyle;
  source: "upload" | "generated";
  status: "draft" | "ready";
  consent: boolean;
  photos: PersonaPhoto[];
  products: number;
  is_default: boolean;
  groups: string[];
  usage: { total: number; own: number; groups: number; project: number };
  job: { state: "running" | "error"; note: string; error: string; mode: string } | null;
}

export interface PersonaGroupTree {
  name: string;
  count: number;
  subs: { name: string; count: number }[];
}

export interface PersonaListing {
  personas: Persona[];
  default_id: number;
  groups: PersonaGroupTree[];
  conflicts: Record<string, string[]>;
}

export interface PresetRef {
  id: number;
  name: string;
  total: number;
  quality: string;
  plan_mode?: "auto" | "manual";
}

export type BlockKey = "studio" | "detail" | "worn" | "full" | "lifestyle";
export type QualityKey = "draft" | "standard" | "premium" | "custom";
export type MarketKey = "none" | "wb" | "ozon" | "ymarket" | "custom";
export type StrictnessKey = "strict" | "normal" | "critical";

export interface PresetMarket {
  key: MarketKey;
  cover: boolean;
  aspect?: string;
  min_side?: number;
  cover_bg?: string;
  cover_fill?: string;
  cover_extra?: string;
}

export interface Preset {
  /** общий пресет сервиса (создал мастер); пользователь может только скопировать его */
  shared?: boolean;
  id: number;
  name: string;
  description: string;
  quality: QualityKey;
  custom: Record<string, string | number | boolean>;
  plan: Record<BlockKey, number>;
  market: PresetMarket;
  strictness: StrictnessKey;
  plan_mode: "auto" | "manual";
  manual: ManualItem[];
  block_models: Partial<Record<BlockKey, string>>;
  total: number;
  is_default: boolean;
  products: number;
}

export interface PresetListing {
  presets: Preset[];
  default_id: number;
  quality: { key: QualityKey; name: string; hint: string; settings: Record<string, unknown> }[];
  blocks: { key: BlockKey; name: string; max: number }[];
  categories: { name: string; count: number; subs: { name: string; count: number }[] }[];
  no_subcategory: number;
  markets: { key: MarketKey; name: string; aspect: string; min_side: number; hint: string; cover_bg: string; cover_fill: string; cover_extra: string }[];
  aspects: string[];
  strictness: { key: StrictnessKey; name: string; hint: string }[];
  model_stats: { block: BlockKey; model: string; n: number; avg_cost: number; first_pass: number | null }[];
}

export interface ManualItem {
  title: string;
  prompt: string;
  block: BlockKey;
  count: number;
  model: string;
}

export interface PresetApplyResult {
  products: number;
  instant: number;
  need_profile: number;
  frames: number | null;
  rebuilt?: number;
  queued?: number;
}

export interface StyleRef {
  id: number;
  name: string;
  note: string;
  description: string;
  blocks: string[];
  status: "draft" | "ready";
  photos: { id: number; asset: string }[];
  products: number;
  is_default: boolean;
  job: { state: "running" | "error"; error: string } | null;
}

export interface StyleListing {
  refs: StyleRef[];
  default_id: number;
  blocks: { key: string; name: string }[];
}

/** Версия кадра: генерация или правка по промпту. */
export interface FrameVersion {
  id: number;
  asset: string | null;
  current: boolean;
  pending: boolean;
  outcome: string;
  edit: string;
  source: number | null;
  created: string | null;
  qc: "pass" | "fail" | null;
  model?: string;
  provider?: string;
  cost?: number;
  seconds?: number;
}

export interface AdminOverview {
  balance: number | null;
  balance_error: string;
  spent: { session: number; project: number; org: number };
  by_kind: { kind: string; name: string; calls: number; sum: number }[];
  by_model: { model: string; calls: number; sum: number; avg: number }[];
  by_day: { day: string; sum: number }[];
  generations: { count: number; avg_cost: number; avg_seconds: number };
  model_stats: { block: string; model: string; n: number; avg_cost: number; first_pass: number | null }[];
  pending: number;
  errors_24h: number;
  metrics: Metrics;
  queue: { parallel: number; max: number };
  model: { model: string; providers: string; resolution: string; aspect: string; qc_model: string };
  default_password: boolean;
}

export interface Me {
  id: number;
  email: string;
  name: string;
  role: "master" | "user";
  client: { id: number; name: string; balance: number; billing: boolean } | null;
}

export interface LedgerEntry {
  id: number;
  kind: "topup" | "charge" | "adjust";
  amount: number;
  balance_after: number;
  what: string;
  project_id: number | null;
  created: string | null;
  cost?: number;
  client_id?: number;
  client?: string;
}

export interface AccountBalance {
  reserved: number; available: number;
  balance: number | null;
  billing: boolean;
  spent_month: number;
  entries: LedgerEntry[];
}

export interface SiteUser {
  id: number;
  email: string;
  name: string;
  role: "master" | "user";
  active: boolean;
  last_login: string | null;
  created: string | null;
  client: {
    id: number; name: string; balance: number; billing: boolean; markup: number | null; markup_effective: number;
    key_id: number | null; key_name: string; projects: number; charged_month: number; cost_month: number;
  } | null;
}

export interface UsersListing {
  users: SiteUser[];
  unassigned_clients: { id: number; name: string; projects: number }[];
  markup: number;
}

export interface PolzaKeyView {
  id: number;
  name: string;
  mask: string;
  active: boolean;
  shared: boolean;
  note: string;
  in_pool: boolean;
  pinned: string[];
  serves: string[];
  balance: number | null;
  balance_error: string;
}

export interface KeysListing {
  keys: PolzaKeyView[];
}

export interface FinanceView {
  summary: { revenue_month: number; cost_month: number; topups_month: number; revenue_all: number; cost_all: number;
    balances: number; margin_month: number };
  entries: LedgerEntry[];
}


export interface GenerationEstimate {
  count: number; products: number; generation: number; checking: number; expected: number; upper: number;
  reserved: number; available: number; accepted_frames: number; complete_products: number;
  cost_per_accepted: number | null; cost_per_complete: number | null;
  groups: { model: string; block: string; category: string; frames: number; samples: number; source: string }[];
  note: string;
}
export interface ReviewItem {
  id: number; product_id: number; sku: string; position: number; generation: number; asset: string;
  status: string; references: string[]; defects: string[];
  details: { text: string; category: string; severity: string }[];
}
export interface ReviewListing { items: ReviewItem[]; total: number; page: number; page_size: number }
