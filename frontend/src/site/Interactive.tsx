import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { PriceList } from "../api/types";
import { BOOT } from "./SiteLayout";

const rub = (v: number) => `${Math.round(v).toLocaleString("ru-RU")} ₽`;
const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Плавное появление блоков с атрибутом data-reveal при прокрутке. Без JS и при «меньше движения» всё видно сразу. */
export function useReveal() {
  useEffect(() => {
    if (reduced() || !("IntersectionObserver" in window)) return;
    document.documentElement.classList.add("reveal-on");
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      }
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    const seen = new WeakSet<Element>();
    const scan = () => document.querySelectorAll("[data-reveal]").forEach((el) => {
      if (!seen.has(el)) { seen.add(el); io.observe(el); }
    });
    scan();
    // блоки, которые появляются позже (цены после загрузки), тоже подхватываются
    const mo = new MutationObserver(scan);
    mo.observe(document.body, { childList: true, subtree: true });
    return () => { io.disconnect(); mo.disconnect(); };
  }, []);
}

/** Шапка становится плотнее после прокрутки; в меню подсвечивается раздел, который сейчас на экране. */
export function useScrollState(ids: string[]) {
  const [scrolled, setScrolled] = useState(false);
  const [active, setActive] = useState("");
  useEffect(() => {
    const onScroll = () => {
      setScrolled(window.scrollY > 8);
      let cur = "";
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top < window.innerHeight * 0.35) cur = id;
      }
      setActive(cur);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  return { scrolled, active };
}

/** Число, которое «досчитывает» до значения, когда появляется на экране. */
export function CountUp({ to, suffix = "", decimals = 0 }: { to: number; suffix?: string; decimals?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [v, setV] = useState(reduced() ? to : 0);
  useEffect(() => {
    if (reduced()) { setV(to); return; }
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const tick = (t: number) => {
        const k = Math.min(1, (t - t0) / 900);
        setV(to * (1 - Math.pow(1 - k, 3)));
        if (k < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to]);
  return <span ref={ref}>{v.toLocaleString("ru-RU", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>;
}

function Boot({ zoom }: { zoom?: boolean }) {
  return (
    <svg className={`boot ${zoom ? "zoom" : ""}`} viewBox="0 0 200 200" aria-hidden="true">
      <ellipse cx="108" cy="178" rx="70" ry="7" className="boot-shadow" />
      <path d={BOOT} className="boot-body" />
      <path d="M115 60h-20M115 74h-20M115 88h-20" className="boot-lace" />
    </svg>
  );
}

const SHOTS: [string, string, boolean?][] = [["s-white", "Белый фон · обложка"], ["s-warm", "Студия · тёплый свет"],
  ["s-detail", "Деталь крупно", true], ["s-room", "Интерьер"]];

/** Первый экран: серия «снимается» на глазах — кадры по очереди проходят генерацию и ИИ-проверку; карточки следуют за курсором. */
export function HeroDemo() {
  const [step, setStep] = useState(reduced() ? 99 : 0);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  useEffect(() => {
    if (reduced()) return;
    const t = window.setInterval(() => setStep((s) => (s >= SHOTS.length * 2 + 3 ? 0 : s + 1)), 900);
    return () => window.clearInterval(t);
  }, []);
  const state = (i: number) => (step >= i * 2 + 2 ? "done" : step >= i * 2 + 1 ? "gen" : step >= i * 2 ? "queue" : "idle");
  const done = SHOTS.filter((_, i) => state(i) === "done").length;
  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (reduced()) return;
    const r = e.currentTarget.getBoundingClientRect();
    setTilt({ x: ((e.clientX - r.left) / r.width - 0.5) * 2, y: ((e.clientY - r.top) / r.height - 0.5) * 2 });
  };
  return (
    <div className="hero-visual" aria-hidden="true" onMouseMove={onMove} onMouseLeave={() => setTilt({ x: 0, y: 0 })}
      style={{ "--tx": tilt.x, "--ty": tilt.y } as CSSProperties}>
      <div className="sheet">
        {SHOTS.map(([cls, cap, zoom], i) => (
          <figure key={cls} className={`shot ${cls} st-${state(i)}`}>
            <Boot zoom={zoom} />
            <figcaption>{cap}</figcaption>
            <i className="ok">ИИ ✓</i>
            <span className="gen-bar"><b /></span>
            <span className="gen-label">{state(i) === "queue" ? "в очереди" : "генерация…"}</span>
          </figure>
        ))}
      </div>
      <div className="hero-chip"><span className="live-dot" />Серия · WB 3:4 · готово {done} из {SHOTS.length}</div>
    </div>
  );
}

const STEPS: [string, string, string][] = [
  ["Загрузите фото товара", "3–5 снимков на телефон с разных сторон. Можно сразу папку или архив всей коллекции — сервис сам разложит фото по артикулам и прочитает этикетки.", "upload"],
  ["Выберите площадку и стиль", "Пресет задаёт качество и набор кадров: белый фон, детали, на модели, в полный рост, интерьер. Добавьте пожелания словами — «тёплый осенний свет».", "setup"],
  ["Получите готовую серию", "Кадры появляются по мере готовности. ИИ проверяет каждый, вы правите словами то, что хочется изменить, и скачиваете ZIP по артикулам.", "result"],
];

/** «Как это работает»: шаги переключаются сами, а по клику — вручную; справа — что вы увидите на этом шаге. */
export function StepsTabs({ presets }: { presets?: PriceList["presets"] }) {
  const [cur, setCur] = useState(0);
  const [auto, setAuto] = useState(!reduced());
  useEffect(() => {
    if (!auto) return;
    const t = window.setInterval(() => setCur((c) => (c + 1) % STEPS.length), 4500);
    return () => window.clearInterval(t);
  }, [auto]);
  return (
    <div className="steps-ui">
      <ol className="steps-list" role="tablist">
        {STEPS.map(([t, d], i) => (
          <li key={t}>
            <button role="tab" aria-selected={cur === i} className={`step-tab ${cur === i ? "on" : ""}`}
              onClick={() => { setCur(i); setAuto(false); }}>
              <span className="step-n">{i + 1}</span>
              <span className="step-text"><b>{t}</b><span>{d}</span></span>
              {cur === i && auto && <span className="step-progress" />}
            </button>
          </li>
        ))}
      </ol>
      <div className="step-stage" aria-live="polite">
        {STEPS[cur][2] === "upload" && (
          <div className="stage stage-upload" key="u">
            <div className="drop"><svg width="28" height="28" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M10 14V4M6 8l4-4 4 4M3.5 16.5h13" /></svg>
              <b>Перетащите фото, папку или ZIP</b><small>сервис разложит снимки по артикулам</small></div>
            <div className="thumbs">{["BX-245", "BX-245", "NW-777", "NW-777", "NW-777", "KD-12"].map((sku, i) => (
              <span key={i} className="thumb" style={{ animationDelay: `${i * 90}ms` }}><Boot /><em>{sku}</em></span>))}</div>
          </div>
        )}
        {STEPS[cur][2] === "setup" && (
          <div className="stage stage-setup" key="s">
            <div className="fake-input"><span className="spark">✦</span>тёплый осенний свет, бежевый фон, акцент на замше<i className="caret" /></div>
            <div className="fake-row"><span className="fake-label">Площадка</span>{["WB", "Ozon", "Я.Маркет", "Авито"].map((m, i) => <span key={m} className={`fake-pill ${i === 0 ? "on" : ""}`}>{m}</span>)}</div>
            <div className="fake-row"><span className="fake-label">Пресет</span>{(presets?.length ? presets.slice(0, 3).map((p) => p.name) : ["Черновик", "Стандарт", "Премиум"]).map((m, i) => <span key={m} className={`fake-pill ${i === 0 ? "on" : ""}`}>{m}</span>)}</div>
            <div className="fake-btn">✦ Сгенерировать {(presets?.[0]?.frames || 8) * 6} кадров</div>
          </div>
        )}
        {STEPS[cur][2] === "result" && (
          <div className="stage stage-result" key="r">
            {SHOTS.concat(SHOTS.slice(0, 2)).map(([cls], i) => (
              <span key={i} className={`mini ${cls}`} style={{ animationDelay: `${i * 120}ms` }}><Boot /><i>ИИ ✓</i></span>
            ))}
            <div className="zip">⬇ Скачать ZIP · папки по артикулам</div>
          </div>
        )}
      </div>
    </div>
  );
}

type MarketKey = "wb" | "ozon" | "ymarket" | "avito";
const MARKETS: Record<MarketKey, { name: string; aspect: string; size: string; rules: string[] }> = {
  wb: { name: "Wildberries", aspect: "3:4", size: "от 900 px", rules: ["товар целиком на чистом нейтральном фоне", "без логотипов, бирок и надписей «хит», «распродажа»", "товар — около 80% кадра"] },
  ozon: { name: "Ozon", aspect: "3:4", size: "900×1200 px", rules: ["реалистичный цветной снимок", "без домашней обстановки и резких теней", "одежду можно показывать на человеке"] },
  ymarket: { name: "Яндекс Маркет", aspect: "3:4", size: "от 900 px", rules: ["лучше на чисто белом фоне", "товар — не меньше 2/3 кадра", "без посторонних людей и водяных знаков"] },
  avito: { name: "Авито", aspect: "4:3", size: "от 1600×1200 px", rules: ["горизонтальный кадр, как в выдаче", "товар по центру с ровными полями", "без телефонов, ссылок и надписей"] },
};

/** Обложка под площадку: выберите площадку — кадр меняет формат, рядом — правила главного фото. */
/** Правила площадки из студии: «3:4, от 700×900 px; главное фото — …; без …» → размер и пункты. */
function fromStudio(x: PriceList["markets"][number]) {
  const [head, ...rest] = x.hint.split(/;\s*/);
  const size = head.split(/,\s*/).filter((t) => /px/.test(t)).join(", ") || `от ${x.min_side} px`;
  const rules = rest.flatMap((r) => r.replace(/^главное фото\s*—\s*/, "").split(/,\s*(?=без )/)).filter(Boolean);
  return { name: x.name, aspect: x.aspect, size, rules };
}

const wide = (a: string) => { const [w, h] = a.split(":").map(Number); return w > h; };

export function MarketDemo({ markets }: { markets?: PriceList["markets"] }) {
  const [m, setM] = useState<MarketKey>("wb");
  const studio = markets?.find((x) => x.key === m);
  const info = studio ? fromStudio(studio) : MARKETS[m];
  return (
    <div className="market-demo">
      <div className="market-pills" role="tablist">
        {(Object.keys(MARKETS) as MarketKey[]).map((k) => (
          <button key={k} role="tab" aria-selected={m === k} className={m === k ? "on" : ""} onClick={() => setM(k)}>{MARKETS[k].name}</button>
        ))}
      </div>
      <div className="market-body">
        <div className="market-frame-wrap">
          <div className="market-frame" style={wide(info.aspect) ? { aspectRatio: info.aspect.replace(":", "/"), height: "auto", width: "min(320px, 100%)" } : { aspectRatio: info.aspect.replace(":", "/") }}>
            <Boot />
            <span className="market-size">{info.aspect} · {info.size}</span>
          </div>
        </div>
        <ul className="market-rules" key={m}>
          <li className="market-title">Главное фото для {info.name}</li>
          {info.rules.map((r, i) => <li key={r} style={{ animationDelay: `${i * 80}ms` }}>{r}</li>)}
          <li className="muted">DreamGoods делает обложку по этим правилам сам, остальные кадры — в том же формате.</li>
        </ul>
      </div>
    </div>
  );
}

/** Калькулятор: сколько стоит съёмка коллекции и какой пакет пополнения подойдёт. */
export function Calculator({ prices, compact }: { prices: PriceList | null; compact?: boolean }) {
  const [products, setProducts] = useState(30);
  const [perProduct, setPerProduct] = useState(6);
  const [tier, setTier] = useState("standard");
  const [preset, setPreset] = useState<string | null>(null);
  const t = prices?.tiers.find((x) => x.key === tier);
  const frames = products * perProduct;
  const total = t ? frames * t.price : 0;
  const pack = prices?.packages.find((p) => p.amount * (1 + p.bonus_rate) >= total) || prices?.packages[prices.packages.length - 1];
  const amount = pack && pack.amount * (1 + pack.bonus_rate) >= total ? pack.amount : Math.ceil(total / 100) * 100;
  const tiers = prices?.tiers || [];
  const presets = prices?.presets || [];
  const usePreset = (p: PriceList["presets"][number]) => { setPreset(p.name); setPerProduct(Math.min(30, p.frames)); setTier(p.quality); };
  return (
    <div className={`calc ${compact ? "compact" : ""}`}>
      <div className="calc-in">
        <label className="calc-field">
          <span>Товаров в коллекции <b>{products}</b></span>
          <input type="range" min={1} max={500} value={products} onChange={(e) => setProducts(+e.target.value)}
            style={{ "--p": `${((products - 1) / 499) * 100}%` } as CSSProperties} />
        </label>
        <label className="calc-field">
          <span>Кадров на товар <b>{perProduct}</b></span>
          <input type="range" min={1} max={30} value={perProduct} onChange={(e) => { setPerProduct(+e.target.value); setPreset(null); }}
            style={{ "--p": `${((perProduct - 1) / 29) * 100}%` } as CSSProperties} />
        </label>
        {presets.length > 0 && (
          <div className="calc-field">
            <span>Пресет студии</span>
            <div className="calc-pills">
              {presets.map((p) => (
                <button key={p.name} type="button" className={preset === p.name ? "on" : ""} onClick={() => usePreset(p)} title={p.description}>
                  {p.name}<small>{p.frames} кадров · {p.quality_name}</small>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="calc-field">
          <span>Качество</span>
          <div className="calc-pills">
            {tiers.map((x) => (
              <button key={x.key} type="button" className={tier === x.key ? "on" : ""} onClick={() => { setTier(x.key); setPreset(null); }}>
                {x.name}<small>{x.price.toLocaleString("ru-RU")} ₽</small>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="calc-out">
        <span className="calc-label">{frames.toLocaleString("ru-RU")} кадров · {preset ? `${preset} · ` : ""}{t?.name || "…"}</span>
        <span className="calc-total">≈ {rub(total)}</span>
        <span className="calc-per">≈ {t ? rub(t.price * perProduct) : "—"} за товар</span>
        {pack && total > 0 && (
          <a className="site-btn light" href={`/pricing?amount=${amount}#packages`}>
            {pack.amount * (1 + pack.bonus_rate) >= total
              ? <>Хватит пакета {rub(pack.amount)}{pack.bonus_rate ? ` (+${Math.round(pack.bonus_rate * 100)}%)` : ""}</>
              : <>Пополнить на {rub(amount)}</>} →
          </a>
        )}
      </div>
    </div>
  );
}
