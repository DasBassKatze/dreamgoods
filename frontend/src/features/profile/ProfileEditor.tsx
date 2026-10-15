import { useEffect, useRef, useState } from "react";
import type { Persona, ProfileData, ProfileResponse, StyleRef } from "../../api/types";
import { Modal } from "../../components/Modal";
import { useUI } from "../../components/ui";
import { useProject } from "../../ProjectContext";

type Kind = "text" | "area" | "list";
interface Field { key: string; label: string; hint?: string; kind?: Kind; placeholder?: string; tall?: boolean }

const PRODUCT: Field[] = [
  { key: "subcategory_ru", label: "Подраздел", placeholder: "Сапоги, Ботинки, Кроссовки…" },
  { key: "summary_ru", label: "Кратко (рус.)" },
  { key: "object", label: "Объект", placeholder: "pair of black over-the-knee boots" },
  { key: "noun", label: "Как называть", placeholder: "boots" },
  { key: "unit", label: "Единица товара", placeholder: "exactly one pair of boots (two boots in total, one on each foot)" },
  { key: "description", label: "Описание", kind: "area", tall: true },
  { key: "identity_parts", label: "Части для сверки", placeholder: "shape, toe, heel, sole, material, color" },
  { key: "fastenings", label: "Застёжки и стороны", kind: "area", placeholder: "a long zip on the inner side of the shaft…" },
  { key: "asymmetric_details", label: "Асимметричные детали", placeholder: "zip, lacing, buckle, strap, pull tab" },
  { key: "key_details", label: "Ключевые детали", hint: "по строке", kind: "list" },
  { key: "ignore", label: "Игнорировать на фото", hint: "ценники, бирки…", kind: "list" },
  { key: "shadow", label: "Тень на белом фоне", placeholder: "the sole" },
  { key: "check_items", label: "Пункты проверки", hint: "с ракурсом, где видно: «… — visible only in inner side views»", kind: "list" },
];

const SHOOT: Field[] = [
  { key: "usage", label: "Использование", placeholder: "worn on the legs of a woman · или none" },
  { key: "close_up", label: "Крупный план", placeholder: "close-up of an adult woman's legs wearing these exact boots…" },
  { key: "person", label: "Человек", kind: "area" },
  { key: "person_noun", label: "Кто", placeholder: "woman" },
  { key: "body_focus", label: "Части тела в кадре", placeholder: "legs, knees and feet" },
  { key: "outfit", label: "Образ" },
  { key: "outfit_visibility", label: "Видимость товара", placeholder: "with the hem above the top of the boots…" },
  { key: "location", label: "Локация" },
  { key: "mood", label: "Настроение поз" },
  { key: "bold_pose", label: "Поза на общем плане" },
  { key: "studio_shots", label: "Кадры на белом фоне", kind: "list" },
  { key: "detail_shots", label: "Детали крупно", kind: "list" },
  { key: "usage_shots", label: "На человеке крупно / в использовании", kind: "list" },
  { key: "scene_shots", label: "В полный рост / общие планы", kind: "list" },
  { key: "lifestyle_shots", label: "Лайфстайл без людей", kind: "list" },
];

const ALL = [...PRODUCT, ...SHOOT];

function toForm(p: ProfileData | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of ALL) {
    const v = p?.[f.key] ?? (f.key === "mood" ? p?.style : undefined);
    out[f.key] = Array.isArray(v) ? v.join("\n") : v == null ? "" : String(v);
  }
  return out;
}

export function ProfileEditor({ productId, onClose }: { productId: number; onClose: () => void }) {
  const { api, reload, run, product, state } = useProject();
  const ui = useUI();
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [category, setCategory] = useState("");
  const [isPair, setIsPair] = useState(false);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [styles, setStyles] = useState<StyleRef[]>([]);
  const productStyle = product(productId)?.style_ref_id ?? null;
  const productPersona = product(productId)?.persona_id ?? null;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    api.getProfile(productId)
      .then((r) => {
        setData(r);
        setForm(toForm(r.profile));
        setCategory(r.profile?.category || r.categories[0]?.key || "");
        setIsPair(!!r.profile?.is_pair);
      })
      .catch((e) => { ui.toast(e.message); closeRef.current(); });
  }, [api, productId, ui]);

  useEffect(() => {
    api.personas().then((r) => setPersonas(r.personas.filter((x) => x.status === "ready"))).catch(() => {});
    api.styles().then((r) => setStyles(r.refs.filter((x) => x.status === "ready"))).catch(() => {});
  }, [api]);

  const setPersona = (v: string) =>
    run(async () => {
      await api.setProductPersona(productId, v ? +v : null);
      await reload();
      ui.toast("Модель для товара сохранена. Чтобы одежда и сцены подобрались под неё — «Пересоставить ИИ»");
    });

  const setStyle = (v: string) =>
    run(async () => {
      await api.setProductStyle(productId, v ? +v : null);
      await reload();
      ui.toast("Оформление товара сохранено. Чтобы локации и настроение подобрались под него — «Пересоставить ИИ»");
    });

  const body = (): ProfileData => {
    const p: ProfileData = { category, is_pair: isPair };
    for (const f of ALL) p[f.key] = f.kind === "list" ? form[f.key].split("\n").map((x) => x.trim()).filter(Boolean) : form[f.key];
    return p;
  };

  const save = (build: boolean) =>
    run(async () => {
      if (build && data?.prompts) {
        const ok = await ui.confirm({
          title: "Пересобрать промпты",
          text: `Заменить ${data.prompts} промптов кадров «${data.sku}» на собранные из профиля? Ваши ручные правки промптов будут заменены, уже сгенерированные картинки не удаляются.`,
          ok: "Заменить",
        });
        if (!ok) return;
      }
      const r = await api.saveProfile(productId, body(), build);
      ui.toast(build ? `Промпты собраны: ${r.prompts}` : "Профиль сохранён — проверка будет учитывать его пункты");
      await reload();
      onClose();
    });

  const regenerate = () =>
    run(async () => {
      const ok = await ui.confirm({ text: "Пересоставить профиль ИИ по фото? Ваши правки профиля будут заменены, промпты кадров не изменятся.", ok: "Пересоставить" });
      if (!ok) return;
      await api.generateProfiles([productId], false);
      ui.toast("Составляю профиль…");
      await reload();
      onClose();
    });

  const field = (f: Field) => (
    <div key={f.key} className="pf-row">
      <label>{f.label}{f.hint && <><br /><span className="hint">{f.hint}</span></>}</label>
      {f.kind === "area" || f.kind === "list" ? (
        <textarea className={f.tall || f.kind === "list" ? "tall" : ""} placeholder={f.placeholder} value={form[f.key] || ""}
          onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
      ) : (
        <input type="text" placeholder={f.placeholder} value={form[f.key] || ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
      )}
    </div>
  );

  const meta = data?.meta;
  return (
    <Modal title={`Профиль товара · ${data?.sku || "…"}`} width={980} onClose={onClose}
      footer={<>
        <button onClick={regenerate}>Пересоставить ИИ</button>
        <span className="spacer" />
        <button onClick={() => save(false)}>Сохранить</button>
        <button className="primary" onClick={() => save(true)}>
          {data?.prompts ? `Сохранить и пересобрать промпты (заменит ${data.prompts})` : "Сохранить и собрать промпты"}
        </button>
      </>}>
      {!data ? <div className="empty">Загрузка…</div> : (
        <>
          {meta && (
            <div className="hint mb10">
              Версия {meta.version} · {meta.source === "ai" ? `составил ${meta.model}` : meta.source === "manual" ? "правка вручную" : "перенесён"} · {meta.created_at}
            </div>
          )}
          <div className="pf">
            <h4>Модель на кадрах</h4>
            <div className="pf-row">
              <label>Человек</label>
              <div>
                <select value={productPersona ?? ""} onChange={(e) => setPersona(e.target.value)}>
                  <option value="">Автоматически — по группе товаров или модель проекта{state.persona ? ` (${state.persona.name})` : ""}</option>
                  {personas.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
                <div className="hint mt4">С моделью клиента её фото идут генератору вместе с фото товара, а поле «Человек» ниже не используется.</div>
              </div>
            </div>
            <div className="pf-row">
              <label>Оформление</label>
              <div>
                <select value={productStyle ?? ""} onChange={(e) => setStyle(e.target.value)}>
                  <option value="">Как в проекте ({state.style_ref ? state.style_ref.name : "не задано"})</option>
                  {styles.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
                <div className="hint mt4">Фото-пример стиля идёт генератору для выбранных в нём видов кадров (обложка — по правилам площадки).</div>
              </div>
            </div>
            <h4>Товар</h4>
            <div className="pf-row">
              <label>Категория</label>
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                {data.categories.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
              </select>
            </div>
            <div className="pf-row">
              <label>Пара</label>
              <label className="check"><input type="checkbox" checked={isPair} onChange={(e) => setIsPair(e.target.checked)} /> товар — пара (левый/правый зеркальные)</label>
            </div>
            {PRODUCT.map(field)}
            <h4>Съёмка</h4>
            {SHOOT.map(field)}
          </div>
          <div className="hint mt8">Профиль используется и для промптов, и для ИИ-проверки: чек-лист категории + «Ключевые детали» + «Пункты проверки».</div>
        </>
      )}
    </Modal>
  );
}
