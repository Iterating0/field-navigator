export type Mode = "auto" | "demo" | "live";
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
}
export interface FieldRelation {
  name: string;
  reason: string;
  confidence: number;
  evidence_paper_ids: string[];
}
export interface CorePaper {
  paper: Paper;
  score: number;
  reason: string;
  signals: Record<string, number>;
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
}

export type ExploreEvent =
  | { type: "status"; stage: "waiting" | "search" }
  | { type: "partial"; stage: "papers" | "map"; field: FieldNode }
  | { type: "complete"; field: FieldNode }
  | { type: "error"; detail: string; status: number };
