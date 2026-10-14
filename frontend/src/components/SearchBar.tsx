import { useEffect, useRef } from "react";
import { ArrowUpRight, LoaderCircle, Search } from "lucide-react";
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
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const focus = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    };
    window.addEventListener("keydown", focus);
    return () => window.removeEventListener("keydown", focus);
  }, []);
  return (
    <form
      className={`search-bar ${variant === "hero" ? "search-hero" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        onSearch();
      }}
    >
      <Search size={18} />
      <input
        ref={input}
        aria-label="搜索科研领域"
        placeholder={
          variant === "hero"
            ? "例如：KTO 界面超导属于哪些研究方向？"
            : "输入领域，或用中文描述研究问题…"
        }
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={1000}
        required
        minLength={2}
      />
      <kbd>Ctrl K</kbd>
      <select
        aria-label="数据模式"
        value={mode}
        disabled={busy}
        onChange={(e) => setMode(e.target.value as Mode)}
      >
        <option value="auto">自动检索</option>
        <option value="live">实时检索</option>
        <option value="demo">离线示例</option>
      </select>
      <button className="primary" disabled={busy || query.trim().length < 2}>
        {busy ? (
          <LoaderCircle className="spin" size={16} />
        ) : (
          <ArrowUpRight size={17} />
        )}
        <span>{busy ? "识别中" : "开始探索"}</span>
      </button>
    </form>
  );
}
