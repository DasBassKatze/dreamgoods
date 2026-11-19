import { DesktopShell } from "./desktop/DesktopShell";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Site } from "./site/Site";
import { UIProvider } from "./components/ui";
import "./styles.css";
import "./desktop/desktop.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UIProvider>
      <DesktopShell><Site /></DesktopShell>
    </UIProvider>
  </StrictMode>,
);
