// The style-book theme variables (--theme-*) first: the shell components depend on them.
import "../vendor/openaec-style-book/themes/themes.css";
import "@openaec/design-tokens/css";
import "@openaec/design-tokens/layouts";
import "@openaec/design-tokens/components";
import "@openaec/shell/css";
import "./ui/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { LocalHost } from "./host/LocalHost";
import { initI18n } from "./i18n";
import { App } from "./ui/App";

initI18n();
const host = new LocalHost(import.meta.env.VITE_OPENBIM_LOKAAL);

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App host={host} />
  </StrictMode>,
);
