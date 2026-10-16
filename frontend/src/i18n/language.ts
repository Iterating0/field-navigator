import type { Language } from "../types/index.ts";

export const LANGUAGE_STORAGE_KEY = "field-navigator-language";
type PreferenceStorage = Pick<Storage, "getItem" | "setItem">;

export function supportedLanguage(value: unknown): Language | null {
  return value === "zh-CN" || value === "en" ? value : null;
}

/** Existing workspaces retain Chinese until the user explicitly changes it. */
export function detectLanguage(
  saved: unknown,
  browserLanguages: readonly string[],
  existingWorkspace = false,
): Language {
  const preference = supportedLanguage(saved);
  if (preference) return preference;
  if (existingWorkspace) return "zh-CN";
  for (const value of browserLanguages) {
    if (/^zh(?:-|$)/i.test(value)) return "zh-CN";
    if (/^en(?:-|$)/i.test(value)) return "en";
  }
  return "zh-CN";
}

export function readLanguage(
  storage: PreferenceStorage | undefined,
  browserLanguages: readonly string[],
): Language {
  try {
    return detectLanguage(
      storage?.getItem(LANGUAGE_STORAGE_KEY),
      browserLanguages,
      !!(
        storage?.getItem("field-navigator-session-v2") ||
        storage?.getItem("field-navigator-session-v1")
      ),
    );
  } catch {
    return detectLanguage(null, browserLanguages);
  }
}

export function saveLanguage(
  storage: PreferenceStorage | undefined,
  language: Language,
): boolean {
  try {
    if (!storage) return false;
    storage.setItem(LANGUAGE_STORAGE_KEY, language);
    return true;
  } catch {
    return false;
  }
}
