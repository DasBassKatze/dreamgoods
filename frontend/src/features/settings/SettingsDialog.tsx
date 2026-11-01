import { useEffect, useState, type ReactNode } from "react";
import type { Settings } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { ASPECTS } from "../../lib/format";
import { useProject } from "../../ProjectContext";
import type { CatalogKind, CatalogPick } from "../catalog/ModelCatalog";

const REASONING: [string, string][] = [
  ["auto", "как решит модель"], ["none", "выключены"], ["minimal", "минимум"],
  ["low", "низкие"], ["medium", "средние"], ["high", "высокие"],
];
const KNOWN_MODELS = ["google/gemini-nano-banana-2.1", "google/gemini-3.1-flash-image", "google/gemini-3-pro-image-preview"];

interface Props {
  onClose: () => void;
  onPickModel: (kind: CatalogKind) => void;
  picked: CatalogPick | null;
}

export function SettingsDialog({ onClose, onPickModel, picked }: Props) {
  const { state, api, reload, run } = useProject();
  const ui = useUI();
  const [v, setV] = useState<Settings>(state.settings);
  const [apiKey, setApiKey] = useState("");
  const [qcKey, setQcKey] = useState("");

  // модель, выбранная в каталоге, сразу видна в форме
  useEffect(() => {
    if (!picked) return;
    setV((cur) => (picked.kind === "qc" ? { ...cur, qc_model: picked.id } : { ...cur, model: picked.id, providers: picked.providers }));
  }, [picked]);

  const set = <K extends keyof Settings>(k: K, value: Settings[K]) => setV((cur) => ({ ...cur, [k]: value }));
  const text = (k: keyof Settings, placeholder = "") => (
    <input type="text" value={String(v[k] ?? "")} placeholder={placeholder} onChange={(e) => set(k, e.target.value as never)} />
  );
  const num = (k: keyof Settings, min: number, max: number, stepN = 1, width?: number) => (
    <input type="number" min={min} max={max} step={stepN} value={Number(v[k] ?? 0)} style={width ? { width } : undefined}
      onChange={(e) => set(k, (+e.target.value || 0) as never)} />
  );
  const check = (k: keyof Settings, label: ReactNode) => (
    <label className="check"><input type="checkbox" checked={!!v[k]} onChange={(e) => set(k, e.target.checked as never)} /> {label}</label>
  );

  const save = () =>
    run(async () => {
      const { has_key: _a, has_qc_key: _b, ...values } = v;
      const body: Record<string, unknown> = { ...values };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      if (qcKey.trim()) body.qc_api_key = qcKey.trim();
      await api.saveSettings(body);
      ui.toast("Настройки сохранены");
      await reload();
      onClose();
    });

  const resetChecklist = () => run(async () => set("qc_checklist", (await api.settingsDefaults()).qc_checklist));

  return (
    <Modal title="Настройки" width={780} onClose={onClose}
      footer={<><span className="spacer" /><button onClick={onClose}>Отмена</button><button className="primary" onClick={save}>Сохранить</button></>}>
      <div className="form grid">
        <Row label="API-ключ Polza">
          <input type="password" value={apiKey} placeholder="оставьте пустым, чтобы не менять" onChange={(e) => setApiKey(e.target.value)} />
          <div className="hint">{v.has_key ? "Ключ сохранён (общий для всех проектов организации)" : "Ключ не найден — вставьте его сюда"}</div>
        </Row>
        <Row label="Модель по умолчанию">
          <div className="row nowrap">
            <input type="text" list="known-models" value={v.model} onChange={(e) => set("model", e.target.value)} />
            <button type="button" onClick={() => onPickModel("image")}>Каталог Polza…</button>
          </div>
          <datalist id="known-models">{KNOWN_MODELS.map((m) => <option key={m} value={m} />)}</datalist>
          <div className="hint">модель по умолчанию — работает, если в пресете не выбрана своя. Основную модель и модели по блокам
            выбирают в пресете. ID копируется со страницы модели на polza.ai</div>
        </Row>
        <Row label="Провайдеры">
          {text("providers")}
          <div className="hint">через запятую, например <code>google-ai-studio</code>; пусто — выбирает Polza</div>
        </Row>
        <Row label="Запасной провайдер">{check("fallback", "разрешить переход к другому провайдеру при сбое")}</Row>
        <Row label="Формат кадра">
          <select value={v.aspect} onChange={(e) => set("aspect", e.target.value)}>
            {ASPECTS.map(([a, name]) => <option key={a} value={a}>{name}</option>)}
          </select>
        </Row>
        <Row label="Разрешение">
          <select value={v.resolution} onChange={(e) => set("resolution", e.target.value)}>
            {["1K", "2K", "4K"].map((a) => <option key={a}>{a}</option>)}
          </select>
        </Row>
        <Row label="Референсов в генерацию">{num("max_refs", 1, 14)}</Row>
        <Row label="Сжатие референсов, px">{num("ref_side", 512, 3072, 128)}</Row>
        <Row label="Серия кадров">{check("series", "снимать кадры товара как одну фотосессию: сначала опорный кадр (обложка, первый кадр на модели), остальные — по нему с тем же светом, цветом и образом; в полный рост — разные эмоции модели")}</Row>
        <Row label="Передача фото">{check("upload_refs", "загружать фото-референсы в хранилище Polza и передавать ссылками — меньше сбоев «Image fetch failed», запросы легче")}</Row>
        <Row label="Фото модели клиента">
          {num("persona_refs", 1, 4)}
          <div className="hint">сколько фото модели отправлять вместе с фото товара (кадры с человеком). Саму модель выбирают в «Модель»</div>
        </Row>

        <h4>ИИ-проверка</h4>
        <Row label="Проверять кадры">{check("qc_enabled", "сверять каждую генерацию с референсами")}</Row>
        <Row label="Модель проверки">
          <div className="row nowrap">
            {text("qc_model")}
            <button type="button" onClick={() => onPickModel("qc")}>Каталог Polza…</button>
          </div>
          <div className="hint">vision-модель, которая видит картинки (Gemini Flash, GPT, Qwen-VL…)</div>
        </Row>
        <Row label="Адрес API проверки">
          {text("qc_base_url", "пусто = Polza")}
          <div className="hint">для своей модели: <code>http://сервер:8000/v1</code> (vLLM) или <code>http://сервер:11434/v1</code> (Ollama)</div>
        </Row>
        <Row label="Ключ API проверки">
          <input type="password" value={qcKey} placeholder="пусто = ключ Polza" onChange={(e) => setQcKey(e.target.value)} />
          {v.has_qc_key && <div className="hint">Отдельный ключ сохранён</div>}
        </Row>
        <Row label="Как решается"><div className="hint pt6">модель возвращает только причины брака; нет причин — кадр принят</div></Row>
        <Row label="Автоперегенерация">{check("qc_autoregen", "переделывать брак автоматически (выкл — брак сразу уходит вам на ручную проверку)")}</Row>
        <Row label="Попыток перегенерации">
          {num("qc_retries", 0, 3)}
          <div className="hint">сколько раз переделать брак, прежде чем отдать кадр на ручную проверку</div>
        </Row>
        <Row label="Отдельный подсчёт">{check("qc_count", "второй запрос: модель пересчитывает товар, людей и части тела. Дороже; включайте, если сверка пропускает лишнюю ногу или лишний товар")}</Row>
        <Row label="Модель подсчёта">{text("qc_count_model", "пусто = та же модель проверки")}</Row>
        <Row label="Рассуждения модели">
          <div className="row">
            <label>сверка <Reasoning value={v.qc_reasoning} onChange={(x) => set("qc_reasoning", x)} /></label>
            <label>подсчёт <Reasoning value={v.qc_count_reasoning} onChange={(x) => set("qc_count_reasoning", x)} /></label>
          </div>
          <div className="hint">«размышления» оплачиваются как ответ модели. Выключены — дешевле и быстрее</div>
        </Row>
        <Row label="Строгость (без пресета)">
          <select value={v.qc_strictness || "normal"} onChange={(e) => set("qc_strictness", e.target.value)}>
            <option value="strict">строго — любое заметное отличие</option>
            <option value="normal">обычно — то, что портит карточку</option>
            <option value="critical">только критичное</option>
          </select>
          <div className="hint">у товаров с пресетом действует строгость пресета</div>
        </Row>
        <Row label="Каскад">{check("qc_cascade", "если кадр уже провален, следующие этапы проверки не запускать")}</Row>
        <Row label="Кадр для проверки, px">
          {num("qc_image_side", 768, 4096, 256)}
          <div className="hint">кадр отправляется целиком; больше — лучше видны мелкие детали, но запрос дороже</div>
        </Row>
        <Row label="Мин. сторона кадра, px">{num("qc_min_side", 0, 4096, 100)}</Row>

        <h4>Профиль товара и промпты по фото</h4>
        <Row label="Модель профиля">
          {text("profile_model", "пусто = модель проверки")}
          <div className="hint">vision-модель, которая смотрит на фото и составляет профиль; адрес и ключ — те же, что у проверки</div>
        </Row>
        <Row label="План без пресета">
          <div className="row">
            <label>белый фон {num("plan_a", 0, 8, 1, 60)}</label>
            <label>в использовании {num("plan_b", 0, 6, 1, 60)}</label>
            <label>общий план {num("plan_c", 0, 4, 1, 60)}</label>
          </div>
        </Row>
        <Row label="Чек-лист без профиля">
          <textarea value={v.qc_checklist} onChange={(e) => set("qc_checklist", e.target.value)} />
          <div className="row"><button type="button" onClick={resetChecklist}>Вернуть чек-лист обуви</button></div>
        </Row>
      </div>
    </Modal>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <label className="form-label">{label}</label>
      <div>{children}</div>
    </>
  );
}

function Reasoning({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {REASONING.map(([k, n]) => <option key={k} value={k}>{n}</option>)}
    </select>
  );
}
