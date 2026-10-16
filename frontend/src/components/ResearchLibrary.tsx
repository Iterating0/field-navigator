import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  Check,
  ChevronDown,
  Download,
  ExternalLink,
  Search,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import {
  MAX_NOTE_LENGTH,
  safeHttpUrl,
  type SavedPaper,
  type SavedPaperPatch,
} from "../state/library";
import { abstractProvenanceLabel } from "../state/provenance";
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
  /** Optional so the parent can return to the research entry point from an empty library. */
  onExplore?: () => void;
  /** Optional because the root can retain the most recently removed paper for an undo action. */
  onUndoRemove?: () => void;
  canUndoRemove?: boolean;
}

type StatusFilter = "all" | "unread" | "read";

const ALL_FIELDS = "__all__";

function notePreview(value: string): string {
  const preview = value.replace(/\s+/g, " ").trim();
  return preview.length > 88 ? `${preview.slice(0, 88)}…` : preview;
}

export function ResearchLibrary({
  items,
  onUpdate,
  onRemove,
  onClear,
  onExport,
  onClose,
  onUndoClear,
  onExplore,
  onUndoRemove,
  canUndoRemove = false,
}: ResearchLibraryProps) {
  const { t, i18n } = useTranslation("workspace");
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
  const hasActiveFilters =
    Boolean(query.trim()) || status !== "all" || field !== ALL_FIELDS;
  const resetFilters = () => {
    setQuery("");
    setStatus("all");
    setField(ALL_FIELDS);
  };
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
  const fieldSeparator = i18n.resolvedLanguage?.startsWith("en") ? ", " : "、";
  const language = i18n.resolvedLanguage === "en" ? "en" : "zh-CN";
  const summary = t("library.summary", {
    papers: t("library.papers", { count: items.length }),
    unread: t("library.unread", { count: unreadCount }),
  });

  return (
    <section
      className="research-library"
      aria-labelledby="research-library-title"
    >
      <header className="library-header">
        <div className="library-header-main">
          <span className="library-eyebrow">
            <BookOpen size={14} />
            {t("library.eyebrow")}
          </span>
          <h1 id="research-library-title">{t("library.title")}</h1>
          <p>{summary}</p>
        </div>
        <div className="library-header-actions">
          <button
            className="library-button library-button-primary"
            onClick={onExport}
            disabled={!items.length}
          >
            <Download size={15} />
            {t("library.export")}
          </button>
          {onClose && (
            <button
              className="library-icon-button"
              onClick={onClose}
              aria-label={t("library.closeAria")}
              title={t("library.closeAria")}
            >
              <X size={18} />
            </button>
          )}
        </div>
      </header>

      <div
        className="library-toolbar"
        role="search"
        aria-label={t("library.searchRoleAria")}
      >
        <label className="library-search">
          <Search size={15} />
          <span className="sr-only">{t("library.searchSrOnly")}</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("library.searchPlaceholder")}
            aria-label={t("library.searchAria")}
            autoComplete="off"
          />
        </label>
        <label className="library-filter">
          <span>{t("library.statusLabel")}</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as StatusFilter)}
            aria-label={t("library.statusAria")}
          >
            <option value="all">{t("library.all")}</option>
            <option value="unread">{t("library.unread")}</option>
            <option value="read">{t("library.read")}</option>
          </select>
        </label>
        <label className="library-filter">
          <span>{t("library.fieldLabel")}</span>
          <select
            value={field}
            onChange={(event) => setField(event.target.value)}
            aria-label={t("library.fieldAria")}
          >
            <option value={ALL_FIELDS}>{t("library.allFields")}</option>
            {fields.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <div className="library-toolbar-spacer" />
        <span className="library-result-count" aria-live="polite">
          {hasActiveFilters
            ? t("library.resultCountFiltered", {
                visibleCount: visible.length,
                totalCount: items.length,
              })
            : t("library.resultCountAll", { count: items.length })}
        </span>
        <button
          className={`library-button library-clear-button ${confirmClear ? "is-confirming" : ""}`}
          onClick={handleClear}
          onBlur={() => setConfirmClear(false)}
          disabled={!items.length}
        >
          <Trash2 size={14} />
          {confirmClear ? t("library.clearConfirm") : t("library.clear")}
        </button>
      </div>

      {undoVisible && onUndoClear && (
        <div className="library-notice" role="status">
          <span>{t("library.clearNotice")}</span>
          <button
            className="library-inline-button"
            onClick={() => {
              onUndoClear();
              setUndoVisible(false);
            }}
          >
            <RotateCcw size={13} />
            {t("library.undo")}
          </button>
        </div>
      )}
      {canUndoRemove && onUndoRemove && (
        <div className="library-notice library-notice-neutral" role="status">
          <span>{t("library.removeNotice")}</span>
          <button className="library-inline-button" onClick={onUndoRemove}>
            <RotateCcw size={13} />
            {t("library.undoRemove")}
          </button>
        </div>
      )}

      <div className="library-list">
        {visible.length ? (
          visible.map((item, index) => {
            const url = safeHttpUrl(item.paper.url);
            const abstract = (
              item.paper as typeof item.paper & { abstract?: string }
            ).abstract;
            const noteId = `library-note-${index}-${item.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
            return (
              <article
                className={`library-card ${item.status === "read" ? "is-read" : ""}`}
                key={item.id}
              >
                <div className="library-card-topline">
                  <span
                    className="library-status-pill"
                    data-status={item.status}
                  >
                    <span className="library-status-dot" aria-hidden="true" />
                    {item.status === "read"
                      ? t("library.readStatus")
                      : t("library.toReadStatus")}
                  </span>
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
                <div className="library-paper-meta">
                  <span className="library-authors">
                    {item.paper.authors.length
                      ? item.paper.authors.join(", ")
                      : t("library.authorsMissing")}
                  </span>
                  <span className="library-meta">
                    {item.paper.year ?? t("library.yearMissing")} ·{" "}
                    {item.paper.journal || t("library.sourceMissing")}
                  </span>
                </div>
                <details className="library-details">
                  <summary>
                    <span className="library-details-summary-main">
                      <ChevronDown size={14} aria-hidden="true" />
                      <span>{t("library.details")}</span>
                    </span>
                    <span
                      className={`library-details-summary-state ${item.note ? "has-note" : ""}`}
                    >
                      {item.note
                        ? t("library.hasNote", {
                            preview: notePreview(item.note),
                          })
                        : t("library.detailsEmpty")}
                    </span>
                  </summary>
                  <div className="library-details-body">
                    {(item.fields.length > 0 || item.reason) && (
                      <div className="library-source">
                        <span className="library-source-label">
                          {t("library.basis")}
                        </span>
                        <strong>
                          {item.fields.length
                            ? item.fields.join(fieldSeparator)
                            : t("library.fieldsMissing")}
                        </strong>
                        <span>{item.reason || t("library.reasonMissing")}</span>
                      </div>
                    )}
                    {abstract && (
                      <details className="library-abstract">
                        <summary>
                          <span>{t("library.abstract")}</span>
                          <ChevronDown size={14} aria-hidden="true" />
                        </summary>
                        {item.paper.abstract_source_record_id &&
                          item.paper.abstract_source_record_id !==
                            item.paper.id && (
                            <small className="library-source-label">
                              {abstractProvenanceLabel(item.paper, language)}
                            </small>
                          )}
                        <p>{abstract}</p>
                      </details>
                    )}
                    <label className="library-notes" htmlFor={noteId}>
                      <span className="library-note-heading">
                        <span>{t("library.notes")}</span>
                        <small>
                          {t("library.noteLength", {
                            count: item.note.length,
                            max: MAX_NOTE_LENGTH,
                          })}
                        </small>
                      </span>
                      <textarea
                        id={noteId}
                        value={item.note}
                        maxLength={MAX_NOTE_LENGTH}
                        placeholder={t("library.notePlaceholder")}
                        aria-label={t("library.noteAria", {
                          title: item.paper.title,
                        })}
                        onChange={(event) =>
                          onUpdate(item.id, { note: event.target.value })
                        }
                      />
                    </label>
                  </div>
                </details>
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
                    {item.status === "read"
                      ? t("library.markUnread")
                      : t("library.markRead")}
                  </button>
                  <button
                    className="library-inline-button library-remove-button"
                    aria-label={t("library.removeAria", {
                      title: item.paper.title,
                    })}
                    onClick={() => onRemove(item.id)}
                  >
                    <Trash2 size={13} />
                    {t("library.remove")}
                  </button>
                </footer>
              </article>
            );
          })
        ) : (
          <div className="library-empty">
            <BookOpen size={28} />
            <strong>
              {items.length
                ? t("library.emptyFiltered")
                : t("library.emptyLibrary")}
            </strong>
            <p>
              {items.length
                ? t("library.emptyFilteredDescription")
                : t("library.emptyLibraryDescription")}
            </p>
            {items.length && hasActiveFilters ? (
              <button className="library-empty-action" onClick={resetFilters}>
                <RotateCcw size={14} />
                {t("library.clearFilters")}
              </button>
            ) : onExplore ? (
              <button className="library-empty-action" onClick={onExplore}>
                <Search size={14} />
                {t("library.explore")}
              </button>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
