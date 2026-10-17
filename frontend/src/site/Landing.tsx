import { useEffect, useState } from "react";
import { publicApi } from "../api/client";
import type { PriceList } from "../api/types";
import { BOOT, SiteLayout } from "./SiteLayout";

const rub = (v: number) => `${v.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} ₽`;

const FEATURES: [string, string, string][] = [
  ["series", "Серия как одна фотосессия", "Все кадры товара — в одном свете, цвете и стиле: первый кадр задаёт образ, остальные снимаются под него."],
  ["check", "ИИ проверяет каждый кадр", "Сверяет кадр с фото товара: форма, цвет, застёжки, швы. Брак переснимается автоматически или ждёт вашего решения."],
  ["edit", "Правка словами", "«Сделай фон светлее», «убери складку на заднике» — меняется только то, что вы попросили. Все версии сохраняются."],
  ["person", "Свои модели", "Сгенерируйте модель по описанию и фото-референсам или загрузите свою — она будет «носить» товары во всех кадрах."],
  ["palette", "Оформление по примеру", "Покажите 1–3 фото в нужном стиле: свет, гамма, настроение перенесутся на ваши кадры без копирования чужих предметов."],
  ["market", "Под правила площадок", "Wildberries, Ozon, Яндекс Маркет, Авито: форматы 3:4, 4:3 и другие, обложка на белом фоне по требованиям площадки."],
  ["batch", "Сотни кадров разом", "Загрузите фото всей коллекции — сервис разложит их по артикулам и снимет параллельно, не дожидаясь каждого кадра."],
  ["zip", "4K, фон и выгрузка", "Улучшение до 4K, удаление фона одной кнопкой, скачивание ZIP с папками по артикулам и отчётом."],
];

const ICONS: Record<string, string> = {
  series: "M3 5h6v8H3zM11 5h6v8h-6zM5 16h10",
  check: "M10 2.5 3.5 5v5c0 3.6 2.8 6.6 6.5 7.5 3.7-.9 6.5-3.9 6.5-7.5V5zM7 10l2 2 4-4",
  edit: "M13.5 3.5l3 3L7 16H4v-3zM11.5 5.5l3 3",
  person: "M10 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3.5 17.5c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5",
  palette: "M10 17a7 7 0 1 1 0-14 7 7 0 0 1 0 14zM10 3v14M10 6.5h6.5M10 10h7M10 13.5h6.5",
  market: "M3 7h14l-1.5 9h-11zM7 7V5a3 3 0 0 1 6 0v2",
  batch: "M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z",
  zip: "M10 3v10M6 9l4 4 4-4M3.5 16.5h13",
};

const STEPS: [string, string][] = [
  ["Загрузите фото товара", "3–5 снимков на телефон с разных сторон. Можно сразу папку или архив всей коллекции — сервис сам разложит фото по артикулам и прочитает этикетки."],
  ["Выберите площадку и стиль", "Пресет задаёт качество и набор кадров: белый фон, детали, на модели, в полный рост, интерьер. Добавьте пожелания словами — «тёплый осенний свет»."],
  ["Получите готовую серию", "Кадры появляются по мере готовности. ИИ проверяет каждый, вы правите словами то, что хочется изменить, и скачиваете ZIP по артикулам."],
];

const FAQ: [string, string][] = [
  ["Нужна ли профессиональная съёмка?", "Нет. Достаточно чётких фото на телефон при хорошем свете: спереди, сзади, сбоку и деталь. Чем лучше видны детали, тем точнее кадры."],
  ["Товар на кадрах будет совпадать с настоящим?", "Каждый кадр сверяется с вашими фото: форма, цвет, материал, фурнитура. Если ИИ находит расхождение, кадр переснимается или попадает к вам «на проверку» — решение за вами."],
  ["Сколько ждать?", "Обычно от 20 секунд до пары минут на кадр. Кадры снимаются параллельно, поэтому коллекция из сотни товаров не стоит в очереди по одному."],
  ["Как оплачивать?", "Пополняете баланс в рублях и платите только за готовые операции — без подписки. Цену видно до запуска, списание — после выполнения."],
  ["Сгорает ли баланс?", "Нет, деньги на балансе не сгорают и не обнуляются."],
  ["Подойдёт ли агентству?", "Да: под каждого клиента — отдельный кабинет со своим входом, балансом, проектами и моделями, а у вас — общие отчёты по всем."],
];

/** Главная страница сайта: что умеет DreamGoods, как это работает, цены вкратце и вопросы. */
export function Landing() {
  const [prices, setPrices] = useState<PriceList | null>(null);
  useEffect(() => { publicApi.prices().then(setPrices).catch(() => setPrices(null)); }, []);
  const tier = (k: string) => prices?.tiers.find((t) => t.key === k);
  const from = tier("draft")?.price;

  return (
    <SiteLayout page="home">
      <section className="hero">
        <div className="site-wrap hero-in">
          <div className="hero-text">
            <span className="eyebrow">ИИ-фотостудия для маркетплейсов</span>
            <h1>Карточки товара <span className="grad">без фотосъёмки</span></h1>
            <p className="lead">Загрузите несколько фото товара — DreamGoods снимет серию кадров для Wildberries, Ozon, Маркета
              и Авито: на белом фоне, на модели, в интерьере. Каждый кадр проверяет ИИ.</p>
            <div className="hero-cta">
              <a className="site-btn primary big" href="/studio">Открыть студию</a>
              <a className="site-btn ghost big" href="/pricing">Цены и оплата</a>
            </div>
            <ul className="hero-facts">
              <li><b>{from ? `от ${rub(from)}` : "₽"}</b><span>за кадр, без подписки</span></li>
              <li><b>4 площадки</b><span>форматы и правила обложки</span></li>
              <li><b>1K–4K</b><span>разрешение на выбор</span></li>
            </ul>
          </div>
          <div className="hero-visual" aria-hidden="true">
            <div className="sheet">
              <figure className="shot s-white"><Boot /><figcaption>Белый фон · обложка</figcaption><i className="ok">ИИ ✓</i></figure>
              <figure className="shot s-warm"><Boot /><figcaption>Студия · тёплый свет</figcaption><i className="ok">ИИ ✓</i></figure>
              <figure className="shot s-detail"><Boot zoom /><figcaption>Деталь крупно</figcaption><i className="ok">ИИ ✓</i></figure>
              <figure className="shot s-room"><Boot /><figcaption>Интерьер</figcaption><i className="ok">ИИ ✓</i></figure>
            </div>
            <div className="hero-chip">Серия из 8 кадров · WB 3:4</div>
          </div>
        </div>
      </section>

      <section className="sec" id="how">
        <div className="site-wrap">
          <h2>Как это работает</h2>
          <ol className="steps">
            {STEPS.map(([t, d], i) => (
              <li key={t}><span className="step-n">{i + 1}</span><h3>{t}</h3><p>{d}</p></li>
            ))}
          </ol>
        </div>
      </section>

      <section className="sec alt" id="features">
        <div className="site-wrap">
          <h2>Что умеет DreamGoods</h2>
          <p className="sec-lead">Всё, что нужно для визуала карточки, — в одной студии.</p>
          <div className="feat-grid">
            {FEATURES.map(([k, t, d]) => (
              <article key={k} className="feat">
                <span className="feat-ico"><svg width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6"
                  strokeLinecap="round" strokeLinejoin="round"><path d={ICONS[k]} /></svg></span>
                <h3>{t}</h3>
                <p>{d}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="sec" id="who">
        <div className="site-wrap who">
          <div><h3>Селлерам</h3><p>Карточки новых товаров в день поступления, без фотографа и дизайнера. Обновляйте визуал под сезон за минуты.</p></div>
          <div><h3>Агентствам и дизайнерам</h3><p>Кабинеты для клиентов, общие модели и оформление, отчёты по расходам — ведите десятки брендов в одном месте.</p></div>
          <div><h3>Брендам</h3><p>Единый стиль во всех карточках: свои модели, свой свет и гамма, одинаковая подача на всех площадках.</p></div>
        </div>
      </section>

      <section className="sec alt" id="prices">
        <div className="site-wrap">
          <h2>Цены</h2>
          <p className="sec-lead">Платите за готовые кадры. Переделки брака уже учтены в средней цене.</p>
          <div className="price-cards">
            {(["draft", "standard", "premium"] as const).map((k) => {
              const t = tier(k);
              return (
                <article key={k} className={`pcard ${k === "standard" ? "featured" : ""}`}>
                  {k === "standard" && <span className="pcard-tag">Для карточек</span>}
                  <h3>{t?.name || "…"}</h3>
                  <div className="pcard-price">{t ? rub(t.price) : "—"}<small> / кадр</small></div>
                  <p>{t ? `${t.model} · ${t.resolution}${t.qc ? " · ИИ-проверка" : ""}` : ""}</p>
                  <p className="muted">{t?.note}</p>
                </article>
              );
            })}
          </div>
          <div className="center"><a className="site-btn ghost" href="/pricing">Все цены и пополнение баланса →</a></div>
        </div>
      </section>

      <section className="sec" id="faq">
        <div className="site-wrap narrow">
          <h2>Вопросы</h2>
          <div className="faq">
            {FAQ.map(([q, a]) => (
              <details key={q}><summary>{q}</summary><p>{a}</p></details>
            ))}
          </div>
        </div>
      </section>

      <section className="sec cta-band">
        <div className="site-wrap cta-in">
          <h2>Снимите первую серию сегодня</h2>
          <p>Загрузите фото товара — первые кадры будут готовы через пару минут.</p>
          <a className="site-btn light big" href="/studio">Открыть студию</a>
        </div>
      </section>
    </SiteLayout>
  );
}

function Boot({ zoom }: { zoom?: boolean }) {
  return (
    <svg className={`boot ${zoom ? "zoom" : ""}`} viewBox="0 0 200 200">
      <ellipse cx="108" cy="178" rx="70" ry="7" className="boot-shadow" />
      <path d={BOOT} className="boot-body" />
      <path d="M115 60h-20M115 74h-20M115 88h-20" className="boot-lace" />
    </svg>
  );
}
