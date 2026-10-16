import { useEffect, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowUpRight,
  Bookmark,
  BookOpen,
  Check,
  ChevronDown,
  ExternalLink,
  FileText,
  Info,
  LoaderCircle,
} from "lucide-react";
import { isSavedPaper, safeHttpUrl } from "../state/library";
import type { CorePaper, FieldNode, FieldRelation, Paper } from "../types";
import "./evidence.css";

type DetailTab = "papers" | "overview";
type Translate = (key: string, options?: Record<string, unknown>) => string;

function shortText(value: string, limit = 260) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function evidenceStatus(relation: FieldRelation, t: Translate) {
  if (relation.evidence_status === "supported")
    return { label: t("evidence.statusSupported"), className: "supported" };
  if (relation.evidence_status === "weak")
    return { label: t("evidence.statusWeak"), className: "weak" };
  return { label: t("evidence.statusUnverified"), className: "unverified" };
}

function claimLevel(relation: FieldRelation, t: Translate) {
  if (relation.claim_level === "theory_or_proposed")
    return {
      label: t("evidence.claimTheory"),
      className: "theory",
      title: t("evidence.claimTheoryTitle"),
    };
  if (relation.claim_level === "title_only")
    return {
      label: t("evidence.claimTitleOnly"),
      className: "title-only",
      title: t("evidence.claimTitleOnlyTitle"),
    };
  return {
    label: t("evidence.claimDirection"),
    className: "direction",
    title: t("evidence.claimDirectionTitle"),
  };
}

function basisLabel(value: CorePaper["evidence_basis"], t: Translate) {
  if (value === "abstract") return t("evidence.quoteAbstract");
  if (value === "title") return t("evidence.quoteTitle");
  return t("evidence.statusUnverified");
}

function roleLabel(value: CorePaper["role"], t: Translate) {
  if (value === "primary") return t("detail.rolePrimary");
  if (value === "review") return t("detail.roleReview");
  if (value === "background") return t("detail.roleBackground");
  if (value === "non_research") return t("detail.roleNonResearch");
  return t("detail.roleUnknown");
}

function safeUrl(url: string | null) {
  return safeHttpUrl(url);
}

const signalKeys: Record<string, string> = {
  relevance: "detail.signalRelevance",
  citation: "detail.signalCitation",
  age_normalized: "detail.signalAge",
  shared_references: "detail.signalSharedReferences",
  llm_importance: "detail.signalLlmImportance",
};

function provenanceLabel(paper: Paper, t: Translate) {
  try {
    const record = new URL(paper.abstract_source_record_id ?? "");
    if (
      record.hostname === "api.datacite.org" &&
      record.pathname.startsWith("/dois/")
    )
      return t("evidence.provenanceDatacite");
    if (record.hostname === "arxiv.org" && record.pathname.startsWith("/abs/"))
      return t("evidence.provenanceArxiv");
  } catch {
    // An index alias can identify a version without being a URL.
  }
  return t("evidence.provenanceIndependent");
}

function RelationEvidence({
  relation,
  evidenceById,
  t,
}: {
  relation: FieldRelation;
  evidenceById: Map<string, Paper>;
  t: Translate;
}) {
  const evidence = relation.evidence_paper_ids
    .map((id) => evidenceById.get(id))
    .filter((paper): paper is Paper => Boolean(paper));
  return (
    <details className="evidence-detail__disclosure">
      <summary>
        <span>
          <BookOpen size={13} aria-hidden="true" />
          {t("detail.relationSources", {
            count: relation.evidence_paper_ids.length,
          })}
        </span>
        <ChevronDown size={13} aria-hidden="true" />
      </summary>
      <div>
        {evidence.length ? (
          evidence.map((paper) => {
            const url = safeUrl(paper.url);
            return (
              <div className="evidence-source" key={paper.id}>
                {url ? (
                  <a
                    className="evidence-source__title"
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {paper.title}
                    <ArrowUpRight size={12} aria-hidden="true" />
                  </a>
                ) : (
                  <span className="evidence-source__title">{paper.title}</span>
                )}
                <small className="evidence-source__meta">
                  {paper.year ?? t("evidence.yearUnknown")} ·{" "}
                  {paper.journal || t("evidence.sourceUnavailable")}
                </small>
                {relation.evidence_quotes
                  ?.filter((quote) => quote.paper_id === paper.id)
                  .slice(0, 2)
                  .map((quote, index) => (
                    <p
                      className="evidence-source__quote"
                      key={`${paper.id}:relation-quote:${index}`}
                    >
                      <span className="evidence-source__quote-label">
                        {quote.source === "abstract"
                          ? t("evidence.quoteAbstract")
                          : t("evidence.quoteTitle")}
                      </span>
                      “{quote.quote}”
                    </p>
                  ))}
                {!relation.evidence_quotes?.some(
                  (quote) => quote.paper_id === paper.id,
                ) &&
                  paper.abstract && (
                    <>
                      <p className="evidence-source__quote evidence-source__quote--unverified">
                        <span className="evidence-source__quote-label">
                          {t("evidence.quoteMetadataAbstract")}
                        </span>
                        “{shortText(paper.abstract)}”
                      </p>
                      {paper.abstract_source_record_id &&
                        paper.abstract_source_record_id !== paper.id && (
                          <small className="evidence-source__provenance">
                            {provenanceLabel(paper, t)}
                          </small>
                        )}
                    </>
                  )}
                {paper.abstract_source_record_id &&
                  paper.abstract_source_record_id !== paper.id &&
                  relation.evidence_quotes?.some(
                    (quote) =>
                      quote.paper_id === paper.id &&
                      quote.source === "abstract",
                  ) && (
                    <small className="evidence-source__provenance">
                      {provenanceLabel(paper, t)}
                    </small>
                  )}
              </div>
            );
          })
        ) : (
          <p>{t("detail.oldCache")}</p>
        )}
        <p className="evidence-relation__boundary">
          {t("evidence.boundary")}
          {relation.evidence_warnings?.length
            ? ` ${relation.evidence_warnings.join(" ")}`
            : ""}
        </p>
      </div>
    </details>
  );
}

function OverviewRelations({
  field,
  label,
  items,
  busy,
  onExplore,
  evidenceById,
  t,
}: {
  field: FieldNode;
  label: string;
  items: FieldRelation[];
  busy: boolean;
  onExplore: (name: string) => void;
  evidenceById: Map<string, Paper>;
  t: Translate;
}) {
  return (
    <section className="evidence-overview__section">
      <h3>
        {label}
        <span className="evidence-overview__count">{items.length}</span>
      </h3>
      {items.length ? (
        items.map((relation) => {
          const status = evidenceStatus(relation, t);
          const level = claimLevel(relation, t);
          return (
            <article className="evidence-relation" key={relation.name}>
              <button
                type="button"
                className="evidence-relation__button"
                disabled={busy}
                onClick={() => onExplore(relation.name)}
                aria-label={t("detail.ariaExploreRelation", {
                  name: relation.name,
                })}
              >
                <strong className="evidence-relation__title">
                  <span>
                    {relation.name}
                    <span className="evidence-relation__reason">
                      {relation.reason}
                    </span>
                  </span>
                  <ArrowUpRight size={15} aria-hidden="true" />
                </strong>
                <span className="evidence-relation__meta">
                  <span className="evidence-relation__meta-text">
                    {field.analysis_source === "mock"
                      ? t("evidence.relationSourceDemo")
                      : t("evidence.relationSourceModel")}
                  </span>
                  {field.analysis_source !== "mock" && (
                    <span
                      className={`evidence-relation__status evidence-relation__status--${status.className}`}
                      title={t("detail.safeUrlWarning")}
                    >
                      {status.label}
                    </span>
                  )}
                  <span
                    className="evidence-relation__claim"
                    title={level.title}
                  >
                    {level.label}
                  </span>
                </span>
              </button>
              {relation.evidence_paper_ids.length > 0 && (
                <RelationEvidence
                  relation={relation}
                  evidenceById={evidenceById}
                  t={t}
                />
              )}
            </article>
          );
        })
      ) : (
        <p className="evidence-overview__summary">
          {t("detail.overviewNoRelations")}
        </p>
      )}
    </section>
  );
}

export function DetailPanel({
  field,
  onExplore,
  busy,
  onSavePaper,
  savedPaperIds,
}: {
  field: FieldNode;
  onExplore: (name: string) => void;
  busy: boolean;
  onSavePaper?: (core: CorePaper, fieldName: string) => void;
  savedPaperIds?: string[];
}) {
  const { t, i18n } = useTranslation("results");
  const [tab, setTab] = useState<DetailTab>("papers");
  useEffect(() => {
    document.querySelector(".evidence-detail__scroll")?.scrollTo(0, 0);
  }, [field.id, tab]);

  const evidenceById = new Map(
    [
      ...field.core_papers.map((core) => core.paper),
      ...(field.evidence_papers ?? []),
    ].map((paper) => [paper.id, paper]),
  );
  const tabIds: DetailTab[] = ["papers", "overview"];
  const tabLabels: Record<DetailTab, string> = {
    papers:
      field.phase === "complete"
        ? t("detail.tabPapersComplete")
        : t("detail.tabPapersInitial"),
    overview: t("detail.tabOverview"),
  };

  function moveTab(direction: "next" | "previous" | "first" | "last") {
    const currentIndex = tabIds.indexOf(tab);
    const nextIndex =
      direction === "first"
        ? 0
        : direction === "last"
          ? tabIds.length - 1
          : direction === "next"
            ? (currentIndex + 1) % tabIds.length
            : (currentIndex - 1 + tabIds.length) % tabIds.length;
    const nextTab = tabIds[nextIndex];
    setTab(nextTab);
    document.getElementById(`evidence-tab-${nextTab}`)?.focus();
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      moveTab("next");
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      moveTab("previous");
    } else if (event.key === "Home") {
      event.preventDefault();
      moveTab("first");
    } else if (event.key === "End") {
      event.preventDefault();
      moveTab("last");
    }
  }

  return (
    <aside className="evidence-detail">
      <div className="evidence-detail__top">
        <span className="evidence-detail__eyebrow">
          <BookOpen size={14} aria-hidden="true" />
          {t("detail.eyebrow")}
        </span>
        <h2>{t("detail.title")}</h2>
        <p>{t("detail.subtitle")}</p>
      </div>
      <div
        className="evidence-detail__tabs"
        role="tablist"
        aria-label={t("detail.tabsAria")}
      >
        {tabIds.map((tabId) => (
          <button
            type="button"
            key={tabId}
            id={`evidence-tab-${tabId}`}
            role="tab"
            aria-selected={tab === tabId}
            aria-controls="evidence-tabpanel"
            tabIndex={tab === tabId ? 0 : -1}
            className="evidence-detail__tab"
            onClick={() => setTab(tabId)}
            onKeyDown={onTabKeyDown}
          >
            {tabLabels[tabId]}
            {tabId === "papers" && (
              <span className="evidence-detail__tab-count">
                {field.core_papers.length}
              </span>
            )}
          </button>
        ))}
      </div>
      {tab === "papers" && field.core_papers.length > 1 && (
        <p className="evidence-detail__scroll-hint">
          {t("detail.paperScrollHint", { count: field.core_papers.length })}
        </p>
      )}
      <div
        id="evidence-tabpanel"
        className="evidence-detail__scroll"
        role="tabpanel"
        aria-labelledby={`evidence-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "papers" ? (
          <>
            <div className="evidence-detail__caption" aria-live="polite">
              <span className="evidence-detail__caption-label">
                {field.phase === "complete"
                  ? t("detail.captionRecommended")
                  : busy
                    ? t("detail.captionBusy")
                    : t("detail.captionPending")}
              </span>
              <span
                className="evidence-detail__caption-note"
                title={t("detail.scoreTitle")}
              >
                {t("detail.scoreNote")}
                <Info size={13} aria-hidden="true" />
              </span>
            </div>
            {field.core_papers.length ? (
              field.core_papers.map((core, index) => {
                const url = safeUrl(core.paper.url);
                const abstract = (
                  core.paper as Paper & { abstract?: string | null }
                ).abstract?.trim();
                const saved = isSavedPaper(core.paper, savedPaperIds);
                return (
                  <article
                    className="evidence-paper"
                    key={`${field.id}:${core.paper.id}`}
                  >
                    <div className="evidence-paper__index">
                      {String(index + 1).padStart(2, "0")}
                    </div>
                    <div className="evidence-paper__body">
                      <div className="evidence-paper__meta">
                        <span className="evidence-paper__meta-left">
                          <span className="evidence-paper__year">
                            {core.paper.year ?? t("evidence.yearUnknown")}
                          </span>
                          <span
                            className={`evidence-paper__badge evidence-paper__badge--${core.evidence_basis === "abstract" ? "supported" : core.evidence_basis === "title" ? "weak" : "unverified"}`}
                            title={t("detail.safeUrlWarning")}
                          >
                            {basisLabel(core.evidence_basis, t)}
                          </span>
                          {core.role && (
                            <span
                              className={`evidence-paper__role ${core.role === "non_research" ? "evidence-paper__role--warning" : ""}`}
                            >
                              {roleLabel(core.role, t)}
                            </span>
                          )}
                        </span>
                        <span
                          className="evidence-paper__score"
                          title={t("detail.scoreTitle")}
                          aria-label={t("detail.scoreAria", {
                            score: Math.round(core.score * 100),
                          })}
                        >
                          {t("detail.scoreLabel", {
                            score: Math.round(core.score * 100),
                          })}
                        </span>
                      </div>
                      <div className="evidence-paper__title-row">
                        {url ? (
                          <a
                            className="evidence-paper__title"
                            href={url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {core.paper.title}
                            <ArrowUpRight size={14} aria-hidden="true" />
                          </a>
                        ) : (
                          <span className="evidence-paper__title evidence-paper__title--unavailable">
                            {core.paper.title}
                          </span>
                        )}
                        {onSavePaper && (
                          <button
                            type="button"
                            className={`evidence-paper__save ${saved ? "evidence-paper__save--saved" : ""}`}
                            aria-pressed={saved}
                            aria-label={
                              saved
                                ? t("detail.saveExistingAria", {
                                    field: field.name,
                                  })
                                : t("detail.saveAddAria", {
                                    title: core.paper.title,
                                  })
                            }
                            title={
                              saved
                                ? t("detail.saveExistingTitle")
                                : t("detail.saveAddTitle")
                            }
                            onClick={() => onSavePaper(core, field.name)}
                          >
                            {saved ? (
                              <Check size={14} aria-hidden="true" />
                            ) : (
                              <Bookmark size={14} aria-hidden="true" />
                            )}
                            {saved ? t("detail.saved") : t("detail.save")}
                          </button>
                        )}
                      </div>
                      {!url && (
                        <p className="evidence-paper__link-note">
                          {t("detail.linkUnavailable")}
                        </p>
                      )}
                      <p className="evidence-paper__authors">
                        {core.paper.authors.slice(0, 2).join(", ")}
                        {core.paper.authors.length > 2 ? " et al." : ""}
                      </p>
                      <p className="evidence-paper__journal">
                        {core.paper.journal || t("evidence.sourceUnavailable")}
                        {core.paper.citation_count !== null && (
                          <>
                            {" "}
                            ·{" "}
                            {t("detail.citationCount", {
                              count: core.paper.citation_count,
                            })}
                          </>
                        )}
                      </p>
                      {abstract && (
                        <details className="evidence-detail__disclosure">
                          <summary>
                            <span>
                              <BookOpen size={13} aria-hidden="true" />
                              {t("detail.abstractDisclosure")}
                            </span>
                            <ChevronDown size={13} aria-hidden="true" />
                          </summary>
                          <p>{shortText(abstract, 360)}</p>
                        </details>
                      )}
                      {core.evidence_quote && (
                        <>
                          <p className="evidence-paper__quote">
                            <span className="evidence-paper__quote-label">
                              {core.evidence_basis === "title"
                                ? t("evidence.quoteTitle")
                                : t("evidence.quoteAbstract")}
                            </span>
                            “{core.evidence_quote}”
                          </p>
                          {core.evidence_basis === "abstract" &&
                            core.paper.abstract_source_record_id &&
                            core.paper.abstract_source_record_id !==
                              core.paper.id && (
                              <small className="evidence-paper__provenance">
                                {provenanceLabel(core.paper, t)}
                              </small>
                            )}
                        </>
                      )}
                      {!abstract && !core.evidence_quote && (
                        <p className="evidence-paper__warning">
                          <span className="evidence-paper__warning-label">
                            {t("detail.evidenceState")}
                          </span>
                          {t("detail.evidenceMissing")}
                        </p>
                      )}
                      {core.role === "non_research" && (
                        <p className="evidence-paper__warning">
                          <span className="evidence-paper__warning-label">
                            {t("detail.entryNote")}
                          </span>
                          {t("detail.nonResearch")}
                        </p>
                      )}
                      <details
                        className="evidence-detail__disclosure evidence-detail__disclosure--reason"
                        open={index === 0}
                      >
                        <summary>
                          <span>
                            <FileText size={13} aria-hidden="true" />
                            {t("detail.whyRead")}
                          </span>
                          <ChevronDown size={13} aria-hidden="true" />
                        </summary>
                        <div>
                          <p>{core.reason}</p>
                          <div className="evidence-paper__signals">
                            {Object.entries(core.signals).map(
                              ([key, value]) => (
                                <div
                                  className="evidence-paper__signal"
                                  key={key}
                                >
                                  <span>
                                    {key === "llm_importance" &&
                                    field.analysis_source === "mock"
                                      ? t("detail.demoPriority")
                                      : signalKeys[key]
                                        ? t(signalKeys[key])
                                        : t("detail.signalUnknown", { key })}
                                  </span>
                                  <meter min="0" max="1" value={value} />
                                  <b>{Math.round(value * 100)}</b>
                                </div>
                              ),
                            )}
                          </div>
                        </div>
                      </details>
                    </div>
                  </article>
                );
              })
            ) : (
              <div className="evidence-detail__empty" role="status">
                {busy ? (
                  <LoaderCircle
                    size={25}
                    className="evidence-detail__loading-icon"
                    aria-hidden="true"
                  />
                ) : (
                  <BookOpen size={25} aria-hidden="true" />
                )}
                <h3>
                  {busy
                    ? t("detail.emptyBusyTitle")
                    : t("detail.emptyNoPapersTitle")}
                </h3>
                <p>
                  {busy
                    ? t("detail.emptyBusyCopy")
                    : t("detail.emptyNoPapersCopy")}
                </p>
              </div>
            )}
            <p className="evidence-detail__note">{t("detail.scoreBoundary")}</p>
          </>
        ) : (
          <>
            <section className="evidence-overview__section">
              <span className="evidence-overview__label">
                {t("detail.overviewCurrent")}
              </span>
              <h3>{field.name}</h3>
              <p className="evidence-overview__summary">{field.summary}</p>
            </section>
            <OverviewRelations
              field={field}
              label={t("detail.overviewPrerequisite")}
              items={field.prerequisites}
              busy={busy}
              onExplore={onExplore}
              evidenceById={evidenceById}
              t={t}
            />
            <OverviewRelations
              field={field}
              label={t("detail.overviewSubfield")}
              items={field.subfields}
              busy={busy}
              onExplore={onExplore}
              evidenceById={evidenceById}
              t={t}
            />
            <section className="evidence-overview__section">
              <h3>{t("detail.sourceHeading")}</h3>
              <p className="evidence-overview__source-copy">
                {t("detail.sourcePapersLabel")}
                {field.paper_source === "demo"
                  ? t("detail.sourceDemoPapers")
                  : t("detail.sourceLivePapers")}
                <br />
                {t("detail.sourceDecompositionLabel")}
                {field.analysis_source === "pending"
                  ? busy
                    ? t("detail.sourcePendingBusy")
                    : t("detail.sourcePending")
                  : field.analysis_source === "mock"
                    ? t("detail.sourceDemoAnalysis")
                    : t("detail.sourceLlmAnalysis")}
                <br />
                {t("detail.generatedAt", {
                  date: new Date(field.created_at).toLocaleString(
                    i18n.language.startsWith("en") ? "en-US" : "zh-CN",
                  ),
                })}
              </p>
              {field.warnings.map((warning) => (
                <p className="evidence-overview__warning" key={warning}>
                  {warning}
                </p>
              ))}
            </section>
          </>
        )}
      </div>
      <div className="evidence-detail__bottom">
        <ExternalLink size={13} aria-hidden="true" />
        {field.core_papers.some((core) => safeUrl(core.paper.url))
          ? t("detail.footerHasLinks")
          : t("detail.footerNoLinks")}
      </div>
    </aside>
  );
}
