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
import { WerkplekHost } from "./host/WerkplekHost";
import { initI18n } from "./i18n";
import { App } from "./ui/App";

initI18n();
// In the SuperCloud workspace the bridge offers a channel to the guest page; otherwise the local development server.
const host = WerkplekHost.fromWindow() ?? new LocalHost(import.meta.env.VITE_OPENBIM_LOKAAL);

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App host={host} />
  </StrictMode>,
);
