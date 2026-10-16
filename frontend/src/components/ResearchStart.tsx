import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Bookmark,
  ChevronDown,
  Compass,
  GitBranch,
  Play,
  ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { SearchBar } from "./SearchBar";
import type { Mode } from "../types";
import "./research-start.css";

interface Props {
  query: string;
  setQuery: (query: string) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  resolving: boolean;
  onSearch: () => void;
  onDemo: () => void;
  onContinue?: () => void;
  previousName?: string;
  savedCount: number;
  onLibrary: () => void;
}

const exampleDefinitions = [
  "condensedMatter",
  "singleCell",
  "geneEditing",
  "ai",
] as const;

export function ResearchStart(props: Props) {
  const { t } = useTranslation("workspace");
  const examples = exampleDefinitions.map((key) => ({
    key,
    label: t(`examples.${key}.label`),
    query: t(`examples.${key}.query`),
  }));
  const renderExample = (example: (typeof examples)[number]) => (
    <button
      key={example.query}
      type="button"
      onClick={() => {
        props.setQuery(example.query);
        if (props.mode === "demo") props.setMode("auto");
        document.querySelector<HTMLInputElement>("#research-query")?.focus();
      }}
    >
      <span className="research-start__example-label">{example.label}</span>
      <span>{example.query}</span>
      <ArrowUpRight size={13} aria-hidden="true" />
    </button>
  );

  const modeDescription = {
    label: t(`mode.${props.mode}.label`),
    description: t(`mode.${props.mode}.description`),
  };

  return (
    <div className="research-start">
      <header className="research-start__intro">
        <div>
          <p className="research-start__overline">{t("start.overline")}</p>
          <h1>{t("start.title")}</h1>
          <p className="research-start__intro-copy">{t("start.intro")}</p>
        </div>
      </header>

      <section
        className="research-start__composer"
        aria-labelledby="start-search-title"
      >
        <div className="research-start__section-heading">
          <h2 id="start-search-title">{t("start.question")}</h2>
        </div>

        <SearchBar
          query={props.query}
          setQuery={props.setQuery}
          mode={props.mode}
          setMode={props.setMode}
          busy={props.resolving}
          onSearch={props.onSearch}
          variant="hero"
        />

        <div
          className="research-start__mode-note"
          aria-label={t("start.modeAria")}
        >
          <span>
            <strong>{modeDescription.label}</strong>{" "}
            {modeDescription.description}
          </span>
        </div>

        <div
          className="research-start__examples"
          role="group"
          aria-label={t("start.examplesAria")}
        >
          <span className="research-start__examples-label">
            {t("start.examplesLabel")}
          </span>
          {examples.slice(0, 2).map(renderExample)}
          <details className="research-start__examples-more">
            <summary>
              <span>{t("start.moreExamples")}</span>
              <ChevronDown size={14} aria-hidden="true" />
            </summary>
            <div className="research-start__examples-more-list">
              {examples.slice(2).map(renderExample)}
            </div>
          </details>
        </div>

        <div className="research-start__disclosure">
          <span>
            <ShieldCheck size={14} aria-hidden="true" />
            {t("start.disclosureExternal")}
          </span>
          <span>
            <Bookmark size={14} aria-hidden="true" />
            {t("start.disclosureLocal")}
          </span>
        </div>
      </section>

      <details className="research-start__guide">
        <summary className="research-start__guide-summary">
          <span>
            <span className="research-start__step-label">
              {t("start.guideLabel")}
            </span>
            <strong>{t("start.guideTitle")}</strong>
          </span>
          <span className="research-start__guide-toggle">
            <span className="research-start__guide-closed">
              {t("start.guideClosed")}
            </span>
            <span className="research-start__guide-open">
              {t("start.guideOpen")}
            </span>
            <ChevronDown size={15} aria-hidden="true" />
          </span>
        </summary>
        <div
          className="research-start__workspace"
          aria-label={t("start.guideAria")}
        >
          <button
            type="button"
            className="research-start__map-card"
            onClick={props.onDemo}
            aria-label={t("start.demoCardAria")}
          >
            <div className="research-start__card-heading">
              <div>
                <span className="research-start__step-label">
                  {t("start.examplePath")}
                </span>
                <strong>{t("start.conceptToBranches")}</strong>
              </div>
              <span className="research-start__card-status">
                {t("start.offlineDemoStatus")}
              </span>
            </div>
            <div className="research-start__map-canvas" aria-hidden="true">
              <svg viewBox="0 0 440 235" preserveAspectRatio="none">
                <path d="M90 68 C165 68 150 119 210 119 M90 178 C165 178 150 119 210 119 M210 119 C278 119 281 50 350 50 M210 119 C278 119 281 125 350 125 M210 119 C278 119 281 204 350 204" />
                <circle cx="90" cy="68" r="3" />
                <circle cx="90" cy="178" r="3" />
                <circle cx="210" cy="119" r="4" />
                <circle cx="350" cy="50" r="3" />
                <circle cx="350" cy="125" r="3" />
                <circle cx="350" cy="204" r="3" />
              </svg>
              <span className="research-start__map-node research-start__map-node--pre top">
                {t("start.nonHermitianPhysics")}
                <small>{t("start.prerequisiteConcept")}</small>
              </span>
              <span className="research-start__map-node research-start__map-node--pre bottom">
                {t("start.topologyBands")}
                <small>{t("start.prerequisiteConcept")}</small>
              </span>
              <span className="research-start__map-node research-start__map-node--center">
                <Compass size={17} aria-hidden="true" /> NHSE
                <small>{t("start.exampleTopic")}</small>
              </span>
              <span className="research-start__map-node research-start__map-node--branch first">
                {t("start.researchBranch")}
                <small>{t("start.continueExploring")}</small>
              </span>
              <span className="research-start__map-node research-start__map-node--branch second">
                {t("start.supportingPapers")}
                <small>{t("start.seeSource")}</small>
              </span>
              <span className="research-start__map-node research-start__map-node--branch third">
                {t("start.readingStart")}
                <small>{t("start.saveToLibrary")}</small>
              </span>
            </div>
            <div className="research-start__card-footer">
              <span>{t("start.demoTopic")}</span>
              <span>
                {t("start.openOfflineDemo")}{" "}
                <ArrowUpRight size={14} aria-hidden="true" />
              </span>
            </div>
          </button>

          <aside className="research-start__workflow">
            <div className="research-start__workflow-heading">
              <span className="research-start__step-label">
                {t("start.workflow")}
              </span>
              <h2>{t("start.workflowTitle")}</h2>
              <p>{t("start.workflowIntro")}</p>
            </div>
            <ol className="research-start__workflow-list">
              <li>
                <span>01</span>
                <div>
                  <strong>{t("start.step1Title")}</strong>
                  <p>{t("start.step1Description")}</p>
                </div>
                <Compass size={17} aria-hidden="true" />
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>{t("start.step2Title")}</strong>
                  <p>{t("start.step2Description")}</p>
                </div>
                <GitBranch size={17} aria-hidden="true" />
              </li>
              <li>
                <span>03</span>
                <div>
                  <strong>{t("start.step3Title")}</strong>
                  <p>{t("start.step3Description")}</p>
                </div>
                <BookOpen size={17} aria-hidden="true" />
              </li>
            </ol>
            <div className="research-start__workflow-note">
              <Bookmark size={15} aria-hidden="true" />
              <span>
                <strong>{t("start.localRecordTitle")}</strong>
                <small>{t("start.localRecordDescription")}</small>
              </span>
            </div>
          </aside>
        </div>
      </details>

      <div className="research-start__bottom">
        <div className="research-start__demo-action">
          <button
            type="button"
            className="research-start__demo"
            onClick={props.onDemo}
          >
            <Play size={14} aria-hidden="true" />
            <span>{t("start.demoAction")}</span>
            <ArrowRight size={15} aria-hidden="true" />
          </button>
          <span>{t("start.demoNote")}</span>
        </div>
        {props.onContinue && props.previousName ? (
          <button
            type="button"
            className="research-start__secondary-action"
            onClick={props.onContinue}
          >
            <span>
              {t("start.continuePrevious", { name: props.previousName })}
            </span>
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        ) : props.savedCount > 0 ? (
          <button
            type="button"
            className="research-start__secondary-action"
            onClick={props.onLibrary}
          >
            <span>
              {t("start.savedPapers", {
                count: props.savedCount,
              })}
            </span>
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        ) : (
          <span className="research-start__quiet-note">
            {t("start.quietNote")}
          </span>
        )}
      </div>
    </div>
  );
}
