import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Compass,
  MessageCircle,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { QueryCandidate, QueryResolution } from "../types";
import "./evidence.css";

type Translate = (key: string, options?: Record<string, unknown>) => string;

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

function CandidateEvidence({
  candidate,
  t,
}: {
  candidate: QueryCandidate;
  t: Translate;
}) {
  const hasEvidence = candidate.evidence_papers.length > 0;
  return (
    <div className="evidence-direction__evidence">
      <span className="evidence-direction__evidence-label">
        <BookOpen size={13} aria-hidden="true" />
        {hasEvidence ? t("chooser.evidenceLabel") : t("chooser.methodLabel")}
      </span>
      {hasEvidence ? (
        candidate.evidence_papers.slice(0, 2).map((paper) => {
          const url = safeLink(paper.url);
          return (
            <div className="evidence-direction__source" key={paper.id}>
              {url ? (
                <a
                  className="evidence-direction__source-link"
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {paper.title}
                  <ArrowUpRight size={12} aria-hidden="true" />
                </a>
              ) : (
                <span className="evidence-direction__source-name">
                  {paper.title}
                </span>
              )}
              <small>{paper.year ?? t("evidence.yearUnavailable")}</small>
            </div>
          );
        })
      ) : (
        <p className="evidence-direction__source evidence-direction__source-name">
          {t("chooser.noSavedMatches")}
        </p>
      )}
    </div>
  );
}

export function DirectionChooser({
  resolution,
  onChoose,
  onDismiss,
}: {
  resolution: QueryResolution;
  onChoose: (candidate: QueryCandidate) => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation("results");
  return (
    <section className="evidence-direction" aria-labelledby="direction-title">
      <div className="evidence-direction__heading">
        <div>
          <span className="evidence-direction__eyebrow">
            <Compass size={14} aria-hidden="true" />
            {t("chooser.eyebrow")}
          </span>
          <h2 id="direction-title">
            {resolution.status === "clarify"
              ? t("chooser.titleClarify")
              : t("chooser.titleChoose")}
          </h2>
        </div>
        <button
          type="button"
          className="evidence-direction__dismiss"
          onClick={onDismiss}
          aria-label={t("chooser.dismiss")}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      <p className="evidence-direction__message">{resolution.message}</p>
      {resolution.status === "clarify" ? (
        <div className="evidence-direction__clarify">
          <MessageCircle size={19} aria-hidden="true" />
          <div>
            <strong>{t("chooser.clarifyTitle")}</strong>
            <p className="evidence-direction__clarify-copy">
              {t("chooser.clarifyCopy")}
            </p>
          </div>
        </div>
      ) : resolution.candidates.length ? (
        <>
          <div
            className="evidence-direction__candidates"
            aria-label={t("chooser.ariaCandidates")}
          >
            {resolution.candidates.map((candidate, index) => (
              <article
                key={candidate.query}
                className="evidence-direction__card"
              >
                <span className="evidence-direction__number">
                  {t("chooser.candidateNumber", {
                    number: String(index + 1).padStart(2, "0"),
                  })}
                </span>
                <h3>{candidate.name}</h3>
                <span className="evidence-direction__query">
                  {t("chooser.queryLabel")}
                  {candidate.query}
                </span>
                <p className="evidence-direction__summary">
                  {candidate.summary}
                </p>
                <CandidateEvidence candidate={candidate} t={t} />
                <button
                  type="button"
                  className="evidence-direction__choose"
                  onClick={() => onChoose(candidate)}
                >
                  {t("chooser.choose")}
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              </article>
            ))}
          </div>
          <p className="evidence-direction__note">{t("chooser.note")}</p>
        </>
      ) : (
        <div className="evidence-direction__empty">
          <BookOpen size={25} aria-hidden="true" />
          <h3>{t("chooser.emptyTitle")}</h3>
          <p>{t("chooser.emptyCopy")}</p>
        </div>
      )}
    </section>
  );
}
