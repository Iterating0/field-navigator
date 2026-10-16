export type Mode = "auto" | "demo" | "live";

/** UI/API language. Keep this independent from React so state and export code
 * can use the same stable contract without creating a persistence side effect. */
export type Language = "zh-CN" | "en";
export const DEFAULT_LANGUAGE: Language = "zh-CN";

export function normalizeLanguage(value: unknown): Language {
  return value === "en" ? "en" : DEFAULT_LANGUAGE;
}

export type EvidenceStatus = "supported" | "weak" | "unverified";
export type ClaimLevel =
  "research_direction" | "theory_or_proposed" | "title_only";
export type EvidenceQuoteSource = "abstract" | "title";
export interface EvidenceQuote {
  paper_id: string;
  source: EvidenceQuoteSource;
  quote: string;
}

export type CorePaperBasis = "abstract" | "title" | "unverified";
export type CorePaperRole =
  "primary" | "review" | "background" | "non_research" | "unknown";

export interface Paper {
  id: string;
  title: string;
  year: number | null;
  authors: string[];
  citation_count: number | null;
  doi: string | null;
  url: string | null;
  journal: string | null;
  source: string;
  abstract?: string | null;
  /** OpenAlex work metadata used to explain why a record was selected. */
  work_type?: string | null;
  work_version?: string | null;
  source_record_ids?: string[];
  abstract_source_record_id?: string | null;
  is_retracted?: boolean;
  is_paratext?: boolean;
}
export interface FieldRelation {
  name: string;
  reason: string;
  confidence: number;
  evidence_paper_ids: string[];
  /** Optional quality audit fields. They are absent in pre-audit responses. */
  evidence_status?: EvidenceStatus;
  evidence_quotes?: EvidenceQuote[];
  evidence_warnings?: string[];
  /** Maturity of the relationship claim; missing legacy values mean direction coverage. */
  claim_level?: ClaimLevel;
}
export interface CorePaper {
  paper: Paper;
  score: number;
  reason: string;
  signals: Record<string, number>;
  evidence_basis?: CorePaperBasis;
  evidence_quote?: string | null;
  role?: CorePaperRole;
}
export interface FieldNode {
  id: string;
  name: string;
  summary: string;
  prerequisites: FieldRelation[];
  subfields: FieldRelation[];
  core_papers: CorePaper[];
  paper_source: "openalex" | "demo";
  analysis_source: "llm" | "mock" | "pending";
  phase: "papers" | "map" | "complete";
  candidate_count: number;
  analyzed_paper_count?: number | null;
  warnings: string[];
  created_at: string;
  cache_hit: boolean;
  /** Added after the first cache format; old responses may omit it. */
  evidence_papers?: Paper[];
  /** Quality contract revision. Missing means the pre-audit revision (0). */
  quality_revision?: number;
  /** The user's original question, kept separate from the canonical field name. */
  research_question?: string | null;
  /** Language used when this field was resolved and analysed. */
  language?: Language;
}

export type ExploreEvent =
  | { type: "status"; stage: "waiting" | "search" }
  | { type: "partial"; stage: "papers" | "map"; field: FieldNode }
  | { type: "complete"; field: FieldNode }
  | { type: "error"; detail: string; status: number };

export interface QueryCandidate {
  query: string;
  name: string;
  summary: string;
  evidence_papers: Paper[];
}

export interface QueryResolution {
  query: string;
  status: "ready" | "choose" | "clarify";
  message: string;
  source: "llm" | "alias" | "direct";
  candidates: QueryCandidate[];
  /** Language used for the resolver response. */
  language?: Language;
}
