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
  "m-reports": "M5 2.5h7l3 3v12H5zM12 2.5v3h3M8 14v-3M10.5 14V9M13 14v-2",
  "m-log": "M5 3h10v14H5zM8 7h4M8 10h4M8 13h2",
  "m-settings": "M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM10 2v2.5M10 15.5V18M2 10h2.5M15.5 10H18M4.3 4.3l1.8 1.8M13.9 13.9l1.8 1.8M4.3 15.7l1.8-1.8M13.9 6.1l1.8-1.8",
  logout: "M8 4H4v12h4M12 6.5 15.5 10 12 13.5M15.5 10H8",
  menu: "M3 5h14M3 10h14M3 15h14",
  plus: "M10 4v12M4 10h12",
  spark: "M10 2.5c.6 3.7 1.8 4.9 5.5 5.5-3.7.6-4.9 1.8-5.5 5.5-.6-3.7-1.8-4.9-5.5-5.5 3.7-.6 4.9-1.8 5.5-5.5zM15.5 13l.6 2 2 .6-2 .6-.6 2-.6-2-2-.6 2-.6z",
  coin: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM8 7.5h3a1.5 1.5 0 0 1 0 3H8V7.5zM8 10.5h3.5M8 7.5V13",
  chevron: "M6 8l4 4 4-4",
  bell: "M5 13.5V9a5 5 0 0 1 10 0v4.5l1.5 2h-13zM8.3 17.5a1.9 1.9 0 0 0 3.4 0",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM13.5 13.5 17 17",
  download: "M10 3v10M6 9l4 4 4-4M3.5 16.5h13",
  upscale: "M4 8V4h4M16 12v4h-4M4 4l5 5M16 16l-5-5M12 4h4v4M8 16H4v-4",
  eraser: "M8.5 16.5 3.5 11.5a1.4 1.4 0 0 1 0-2l6-6a1.4 1.4 0 0 1 2 0l5 5a1.4 1.4 0 0 1 0 2l-6.5 6.5zM6 8.5l5.5 5.5M8.5 16.5H17",
  edit: "M13.5 3.5l3 3L7 16H4v-3zM11.5 5.5l3 3",
  close: "M5 5l10 10M15 5 5 15",
  layers: "M10 3 2.5 7 10 11l7.5-4zM2.5 10.5 10 14.5l7.5-4M2.5 14 10 18l7.5-4",
  upload: "M10 14V4M6 8l4-4 4 4M3.5 16.5h13",
  regen: "M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3h-3",
  clock: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM10 6v4l2.5 2",
  image: "M3 4h14v12H3zM3 13l4-4 3 3 2-2 5 5M13 7.5h.01",
  expand: "M8 3H3v5M12 3h5v5M8 17H3v-5M12 17h5v-5",
  folder: "M3 6a1 1 0 0 1 1-1h4l2 2h6a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="ico">
      <path d={P[name] || ""} />
    </svg>
  );
}
