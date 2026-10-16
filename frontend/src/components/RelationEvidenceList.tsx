import { ArrowRight, ArrowUpRight, BookOpen, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { FieldNode, FieldRelation, Paper } from "../types";
import "./evidence.css";

type Translate = (key: string, options?: Record<string, unknown>) => string;

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

function shortText(value: string, limit = 260) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function safeLink(url: string | null) {
  try {
    const parsed = new URL(url || "");
    return ["https:", "http:"].includes(parsed.protocol)
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}

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

function RelationSource({
  paper,
  relation,
  t,
}: {
  paper: Paper;
  relation: FieldRelation;
  t: Translate;
}) {
  const url = safeLink(paper.url);
  const quotes = (relation.evidence_quotes ?? [])
    .filter((quote) => quote.paper_id === paper.id)
    .slice(0, 2);
  return (
    <div className="evidence-source">
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
      {quotes.length ? (
        quotes.map((quote, index) => (
          <p
            className="evidence-source__quote"
            key={`${paper.id}:quote:${index}`}
          >
            <span className="evidence-source__quote-label">
              {quote.source === "abstract"
                ? t("evidence.quoteAbstract")
                : t("evidence.quoteTitle")}
            </span>
            “{quote.quote}”
          </p>
        ))
      ) : paper.abstract ? (
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
      ) : (
        <p className="evidence-source__quote evidence-source__quote--unverified">
          <span className="evidence-source__quote-label">
            {t("evidence.noAbstractEvidence")}
          </span>
          {t("evidence.noAbstractEvidenceCopy")}
        </p>
      )}
      {paper.abstract_source_record_id &&
        paper.abstract_source_record_id !== paper.id &&
        relation.evidence_quotes?.some(
          (quote) => quote.paper_id === paper.id && quote.source === "abstract",
        ) && (
          <small className="evidence-source__provenance">
            {provenanceLabel(paper, t)}
          </small>
        )}
    </div>
  );
}

export function RelationEvidenceList({
  field,
  kind,
  minConfidence,
  onExplore,
  onResetFilters,
}: {
  field: FieldNode;
  kind: "subfields" | "prerequisites";
  minConfidence: number;
  onExplore: (name: string) => void;
  onResetFilters?: () => void;
}) {
  const { t } = useTranslation("results");
  const relations = field[kind].filter(
    (relation) => relation.confidence >= minConfidence,
  );
  const evidence = new Map<string, Paper>(
    [
      ...field.core_papers.map((core) => core.paper),
      ...(field.evidence_papers ?? []),
    ].map((paper) => [paper.id, paper]),
  );
  function sources(relation: FieldRelation) {
    return relation.evidence_paper_ids
      .map((id) => evidence.get(id))
      .filter((paper): paper is Paper => Boolean(paper));
  }

  return (
    <div className="evidence-relations">
      {relations.length ? (
        relations.map((relation) => {
          const status = evidenceStatus(relation, t);
          const level = claimLevel(relation, t);
          const relationSources = sources(relation);
          return (
            <article className="evidence-relation" key={relation.name}>
              <div className="evidence-relation__button">
                <h3 className="evidence-relation__title">
                  <span>
                    {relation.name}
                    <span className="evidence-relation__reason">
                      {relation.reason}
                    </span>
                  </span>
                </h3>
                <span className="evidence-relation__meta">
                  <span className="evidence-relation__meta-text">
                    {field.analysis_source === "mock"
                      ? t("evidence.relationSourceDemo")
                      : t("evidence.relationSourceModel")}
                  </span>
                  {field.analysis_source !== "mock" && (
                    <span
                      className={`evidence-relation__status evidence-relation__status--${status.className}`}
                      title={t("evidence.boundary")}
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
              </div>
              <div className="evidence-relation__actions">
                <details className="evidence-relation__details">
                  <summary>
                    <span>
                      <BookOpen size={13} aria-hidden="true" />
                      {relation.evidence_paper_ids.length
                        ? t("evidence.supportingPapers", {
                            count: relation.evidence_paper_ids.length,
                          })
                        : t("evidence.supportingPapersNone")}
                    </span>
                    <ChevronDown size={13} aria-hidden="true" />
                  </summary>
                  <div>
                    {relationSources.length ? (
                      relationSources.map((paper) => (
                        <RelationSource
                          key={paper.id}
                          paper={paper}
                          relation={relation}
                          t={t}
                        />
                      ))
                    ) : (
                      <p>{t("evidence.incompleteSources")}</p>
                    )}
                    <p className="evidence-relation__boundary">
                      {t("evidence.boundary")}
                      {relation.evidence_warnings?.length
                        ? ` ${relation.evidence_warnings.join(" ")}`
                        : ""}
                    </p>
                  </div>
                </details>
                <button
                  type="button"
                  className="evidence-relation__explore"
                  onClick={() => onExplore(relation.name)}
                >
                  {t("evidence.explore")}
                  <ArrowRight size={14} aria-hidden="true" />
                </button>
              </div>
            </article>
          );
        })
      ) : (
        <div className="evidence-relations__empty">
          <BookOpen size={26} aria-hidden="true" />
          <h3>
            {field.phase !== "complete"
              ? t("evidence.emptyBefore")
              : t("evidence.emptyFiltered")}
          </h3>
          {minConfidence > 0 && field[kind].length > 0 && onResetFilters && (
            <button className="secondary-button" onClick={onResetFilters}>
              {t("evidence.resetFilter")}
            </button>
          )}
          <p>
            {field.phase !== "complete"
              ? t("evidence.pendingNotice")
              : t("evidence.emptyNotice")}
          </p>
        </div>
      )}
    </div>
  );
}
