import { createInstance } from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";
import { zh as appZh, en as appEn } from "./locales/app";
import { zh as workspaceZh, en as workspaceEn } from "./locales/workspace";
import { zh as resultsZh, en as resultsEn } from "./locales/results";
import { readLanguage, saveLanguage } from "./i18n/language";
import type { Language } from "./types";

export const i18n = createInstance();
let preferenceStorage: Storage | undefined;
try {
  preferenceStorage = window.localStorage;
} catch {
  // Language switching still works when browser storage is unavailable.
}
const initialLanguage = readLanguage(preferenceStorage, navigator.languages);

void i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { app: appZh, workspace: workspaceZh, results: resultsZh },
    en: { app: appEn, workspace: workspaceEn, results: resultsEn },
  },
  lng: initialLanguage,
  supportedLngs: ["zh-CN", "en"],
  load: "currentOnly",
  fallbackLng: "zh-CN",
  defaultNS: "app",
  initAsync: false,
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
});

export function useLocale() {
  const { i18n: instance } = useTranslation();
  const language: Language =
    instance.resolvedLanguage === "en" ? "en" : "zh-CN";
  return {
    language,
    setLanguage(next: Language) {
      void instance.changeLanguage(next);
      return saveLanguage(preferenceStorage, next);
    },
  };
}
