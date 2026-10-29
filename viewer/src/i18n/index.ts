import { openaecResources } from "@openaec/i18n";
import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import nl from "./nl.json";

/** Dutch or English (from the browser language), with the shared OpenAEC terms in namespace `openaec`. */
export function initI18n(language: string = navigator.language): typeof i18next {
  void i18next.use(initReactI18next).init({
    resources: {
      nl: { ...openaecResources.nl, app: nl },
      en: { ...openaecResources.en, app: en },
    },
    lng: language.toLowerCase().startsWith("nl") ? "nl" : "en",
    fallbackLng: "nl",
    ns: ["app", "openaec"],
    defaultNS: "app",
    interpolation: { escapeValue: false },
  });
  return i18next;
}
