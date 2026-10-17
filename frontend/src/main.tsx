import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Site } from "./site/Site";
import { UIProvider } from "./components/ui";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UIProvider>
      <Site />
    </UIProvider>
  </StrictMode>,
);
