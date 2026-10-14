import { useMemo, useState } from "react";
import {
  BookOpen,
  Check,
  ChevronDown,
  Download,
  ExternalLink,
  RotateCcw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import {
  MAX_NOTE_LENGTH,
  safeHttpUrl,
  type SavedPaper,
  type SavedPaperPatch,
} from "../state/library";
import "./library.css";

export interface ResearchLibraryProps {
  items: SavedPaper[];
  onUpdate: (id: string, patch: SavedPaperPatch) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
  onExport: () => void;
  onClose?: () => void;
  /** Optional because the root can retain a pre-clear snapshot for an undo action. */
  onUndoClear?: () => void;
}

type StatusFilter = "all" | "unread" | "read";

const ALL_FIELDS = "__all__";

function paperMeta(item: SavedPaper): string {
  return [
    item.paper.year ?? "年份未知",
    item.paper.journal || "来源未提供",
    item.paper.authors.length
      ? item.paper.authors.slice(0, 2).join(", ")
      : "作者未提供",
  ].join(" · ");
}

export function ResearchLibrary({
  items,
  onUpdate,
  onRemove,
  onClear,
  onExport,
  onClose,
  onUndoClear,
}: ResearchLibraryProps) {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [field, setField] = useState(ALL_FIELDS);
  const [query, setQuery] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [undoVisible, setUndoVisible] = useState(false);

  const fields = useMemo(
    () =>
      [...new Set(items.flatMap((item) => item.fields))].sort((a, b) =>
        a.localeCompare(b),
      ),
    [items],
  );
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      if (status === "read" && item.status !== "read") return false;
      if (status === "unread" && item.status !== "to-read") return false;
      if (field !== ALL_FIELDS && !item.fields.includes(field)) return false;
      if (!needle) return true;
      return [
        item.paper.title,
        item.paper.journal ?? "",
        item.paper.authors.join(" "),
        ...item.fields,
        item.reason,
        item.note,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [field, items, query, status]);

  const unreadCount = items.filter((item) => item.status === "to-read").length;
  const handleClear = () => {
    if (!items.length) return;
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    onClear();
    setConfirmClear(false);
    setUndoVisible(Boolean(onUndoClear));
  };

  return (
    <section className="research-library" aria-labelledby="research-library-title">
      <header className="library-header">
        <div>
          <span className="library-eyebrow">
            <BookOpen size={14} />
            LOCAL READING LIST
          </span>
          <h1 id="research-library-title">阅读清单</h1>
          <p>
            {items.length} 篇论文 · {unreadCount} 篇待读 · 只保存在当前浏览器
          </p>
        </div>
        <div className="library-header-actions">
          <button
            className="library-button library-button-primary"
            onClick={onExport}
            disabled={!items.length}
          >
            <Download size={15} />
            导出 Markdown
          </button>
          {onClose && (
            <button
              className="library-icon-button"
              onClick={onClose}
              aria-label="关闭阅读清单"
              title="关闭阅读清单"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </header>

      <div className="library-toolbar">
        <label className="library-search">
          <Search size={15} />
          <span className="sr-only">搜索阅读清单</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索论文、领域或推荐理由"
            aria-label="搜索阅读清单"
          />
        </label>
        <label className="library-filter">
          <span>状态</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as StatusFilter)}
            aria-label="按阅读状态筛选"
          >
            <option value="all">全部</option>
            <option value="unread">待读</option>
            <option value="read">已读</option>
          </select>
        </label>
        <label className="library-filter">
          <span>领域</span>
          <select
            value={field}
            onChange={(event) => setField(event.target.value)}
            aria-label="按所属领域筛选"
          >
            <option value={ALL_FIELDS}>全部领域</option>
            {fields.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <div className="library-toolbar-spacer" />
        <button
          className={`library-button library-clear-button ${confirmClear ? "is-confirming" : ""}`}
          onClick={handleClear}
          onBlur={() => setConfirmClear(false)}
          disabled={!items.length}
        >
          <Trash2 size={14} />
          {confirmClear ? "再次点击确认清空" : "清空"}
        </button>
      </div>

      {undoVisible && onUndoClear && (
        <div className="library-notice" role="status">
          <span>阅读清单已清空，本地数据仍可撤销。</span>
          <button
            className="library-inline-button"
            onClick={() => {
              onUndoClear();
              setUndoVisible(false);
            }}
          >
            <RotateCcw size={13} />
            撤销
          </button>
        </div>
      )}

      <div className="library-list">
        {visible.length ? (
          visible.map((item) => {
            const url = safeHttpUrl(item.paper.url);
            const abstract = (item.paper as typeof item.paper & { abstract?: string })
              .abstract;
            return (
              <article className={`library-card ${item.status === "read" ? "is-read" : ""}`} key={item.id}>
                <div className="library-card-topline">
                  <span className="library-status-pill">
                    {item.status === "read" ? "已读" : "待读"}
                  </span>
                  <span className="library-meta">{paperMeta(item)}</span>
                </div>
                <div className="library-title-row">
                  {url ? (
                    <a
                      className="library-title"
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item.paper.title}
                      <ExternalLink size={14} />
                    </a>
                  ) : (
                    <span className="library-title library-title-unavailable">
                      {item.paper.title}
                    </span>
                  )}
                  {item.paper.doi && (
                    <code className="library-doi">{item.paper.doi}</code>
                  )}
                </div>
                {item.fields.length > 0 && (
                  <details className="library-sources" open={item.fields.length === 1}>
                    <summary>
                      所属领域与推荐理由（{item.fields.length}）
                      <ChevronDown size={14} />
                    </summary>
                    <div className="library-source">
                      <strong>{item.fields.join("、")}</strong>
                      <span>{item.reason}</span>
                    </div>
                  </details>
                )}
                {abstract && (
                  <details className="library-abstract">
                    <summary>
                      查看摘要 <ChevronDown size={14} />
                    </summary>
                    <p>{abstract}</p>
                  </details>
                )}
                <label className="library-notes">
                  <span>个人笔记</span>
                  <textarea
                    value={item.note}
                    maxLength={MAX_NOTE_LENGTH}
                    placeholder="记录你下一步要读什么、想验证什么……"
                    onChange={(event) => onUpdate(item.id, { note: event.target.value })}
                  />
                  <small>{item.note.length}/{MAX_NOTE_LENGTH}</small>
                </label>
                <footer className="library-card-actions">
                  <button
                    className={`library-button ${item.status === "read" ? "is-read" : ""}`}
                    aria-pressed={item.status === "read"}
                    onClick={() =>
                      onUpdate(item.id, {
                        status: item.status === "read" ? "to-read" : "read",
                      })
                    }
                  >
                    <Check size={14} />
                    {item.status === "read" ? "标为待读" : "标为已读"}
                  </button>
                  <button
                    className="library-inline-button library-remove-button"
                    onClick={() => onRemove(item.id)}
                  >
                    <Trash2 size={13} />
                    移除
                  </button>
                </footer>
              </article>
            );
          })
        ) : (
          <div className="library-empty">
            <BookOpen size={28} />
            <strong>{items.length ? "没有符合筛选条件的论文" : "阅读清单还是空的"}</strong>
            <p>
              {items.length
                ? "试试切换领域或阅读状态筛选。"
                : "在论文详情中点击“加入清单”，保存下一步要读的内容。"}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
