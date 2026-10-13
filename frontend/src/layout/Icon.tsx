/** Иконки меню: тонкие линии 1.6px, сетка 20×20. */
const P: Record<string, string> = {
  products: "M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z",
  import: "M10 13V3M6 7l4-4 4 4M3 13v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3",
  presets: "M4 5h12M4 10h12M4 15h12M7 3v4M13 8v4M9 13v4",
  personas: "M10 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3.5 17.5c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5",
  styles: "M10 17a7 7 0 1 1 0-14 7 7 0 0 1 0 14zM10 3v14M10 6.5h6.5M10 10h7M10 13.5h6.5",
  balance: "M3 6h14v10H3zM3 9h14M13.5 12.5h1",
  "m-users": "M7.5 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 17c.6-2.8 2.8-4.5 5.5-4.5S12.4 14.2 13 17M13 3.3a3 3 0 0 1 0 5.4M15 12.8c1.6.6 2.7 2 3 4.2",
  "m-finance": "M7 17V3h4.5a3.5 3.5 0 0 1 0 7H5M5 13.5h7",
  "m-keys": "M7.5 12.5a4 4 0 1 1 3.4-6.1L17 6.4V9h-2v2h-2.4M6.5 8.5h.01",
  "m-analytics": "M3 17h14M5 14V9M9 14V5M13 14v-3M17 14V7",
  "m-log": "M5 3h10v14H5zM8 7h4M8 10h4M8 13h2",
  "m-settings": "M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM10 2v2.5M10 15.5V18M2 10h2.5M15.5 10H18M4.3 4.3l1.8 1.8M13.9 13.9l1.8 1.8M4.3 15.7l1.8-1.8M13.9 6.1l1.8-1.8",
  logout: "M8 4H4v12h4M12 6.5 15.5 10 12 13.5M15.5 10H8",
  menu: "M3 5h14M3 10h14M3 15h14",
  plus: "M10 4v12M4 10h12",
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="ico">
      <path d={P[name] || ""} />
    </svg>
  );
}
