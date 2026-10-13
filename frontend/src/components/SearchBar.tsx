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
}
export function SearchBar({
  query,
  setQuery,
  mode,
  setMode,
  busy,
  onSearch,
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
      className="search-bar"
      onSubmit={(e) => {
        e.preventDefault();
        onSearch();
      }}
    >
      <Search size={18} />
      <input
        ref={input}
        aria-label="搜索科研领域"
        placeholder="输入一个领域，发现它的知识地图…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={180}
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
        <option value="auto">自动模式</option>
        <option value="live">OpenAlex 实时</option>
        <option value="demo">离线演示</option>
      </select>
      <button className="primary" disabled={busy || query.trim().length < 2}>
        {busy ? (
          <LoaderCircle className="spin" size={16} />
        ) : (
          <ArrowUpRight size={17} />
        )}
        <span>{busy ? "探索中" : "探索"}</span>
      </button>
    </form>
  );
}
