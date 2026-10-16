import { useEffect, useId, useRef } from "react";
import { ArrowUpRight, LoaderCircle, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Mode } from "../types";
interface Props {
  query: string;
  setQuery: (v: string) => void;
  mode: Mode;
  setMode: (m: Mode) => void;
  busy: boolean;
  onSearch: () => void;
  variant?: "compact" | "hero";
}
export function SearchBar({
  query,
  setQuery,
  mode,
  setMode,
  busy,
  onSearch,
  variant = "compact",
}: Props) {
  const { t } = useTranslation("workspace");
  const input = useRef<HTMLInputElement>(null);
  const modeHintId = useId();
  const modeHint = t("search.modeHint");
  useEffect(() => {
    const focus = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        const currentInput = input.current;
        const activeModal = document.querySelector<HTMLElement>(
          '[aria-modal="true"]',
        );
        if (
          !currentInput ||
          currentInput.closest("[inert]") ||
          (activeModal && !activeModal.contains(currentInput))
        )
          return;
        e.preventDefault();
        currentInput.focus();
        currentInput.select();
      }
    };
    window.addEventListener("keydown", focus);
    return () => window.removeEventListener("keydown", focus);
  }, []);
  return (
    <form
      className={`search-bar ${variant === "hero" ? "search-bar--hero" : ""}`}
      aria-label={t("search.formAria")}
      onSubmit={(e) => {
        e.preventDefault();
        onSearch();
      }}
    >
      <Search size={18} />
      <input
        ref={input}
        id="research-query"
        aria-label={t("search.inputAria")}
        placeholder={
          variant === "hero"
            ? t("search.heroPlaceholder")
            : t("search.compactPlaceholder")
        }
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={1000}
        required
        minLength={2}
      />
      <kbd>{t("search.shortcut")}</kbd>
      <select
        aria-label={t("search.modeAria")}
        aria-describedby={modeHintId}
        title={modeHint}
        value={mode}
        disabled={busy}
        onChange={(e) => setMode(e.target.value as Mode)}
      >
        <option value="auto">{t("mode.auto.label")}</option>
        <option value="live">{t("mode.live.label")}</option>
        <option value="demo">{t("mode.demo.label")}</option>
      </select>
      <span id={modeHintId} className="sr-only">
        {modeHint}
      </span>
      <button className="primary" disabled={busy || query.trim().length < 2}>
        {busy ? (
          <LoaderCircle className="spin" size={16} />
        ) : (
          <ArrowUpRight size={17} />
        )}
        <span>{busy ? t("search.resolving") : t("search.explore")}</span>
      </button>
    </form>
  );
}
