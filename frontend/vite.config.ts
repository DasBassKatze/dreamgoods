import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Сборка кладётся в dreamgoods/web — оттуда её раздаёт FastAPI (python run_dreamgoods.py).
// В режиме разработки (npm run dev) запросы /api проксируются на запущенный бэкенд.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../dreamgoods/web",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});
