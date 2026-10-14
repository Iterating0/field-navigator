import type {
  ClaimLevel,
  CorePaperBasis,
  CorePaperRole,
  EvidenceQuote,
  EvidenceQuoteSource,
  EvidenceStatus,
  FieldNode,
  Mode,
  Paper,
} from "../types";

/** Versioned local session key. The legacy key is read only for migration. */
export const SESSION_STORAGE_KEY = "field-navigator-session-v2";
export const LEGACY_SESSION_STORAGE_KEY = "field-navigator-session-v1";
/** Bump when recommendation/evidence semantics change. */
export const CURRENT_QUALITY_REVISION = 10;

export type PaperSource = FieldNode["paper_source"];
export type AnalysisSource = FieldNode["analysis_source"];

export interface HistoryEntry {
  name: string;
  parent: string | null;
  mode: Mode;
  research_question?: string;
  created_at?: string;
  paper_source?: PaperSource;
  analysis_source?: AnalysisSource;
}

/**
 * The in-browser session is deliberately small and contains no credentials,
 * provider configuration, or private notes. snapshots are keyed with
 * requestKey(name, mode, researchQuestion), so demo/live explorations and
 * distinct goals within one canonical field cannot collide.
 */
export interface Session {
  history: HistoryEntry[];
  current: string;
  current_research_question?: string;
  mode: Mode;
  snapshots: Record<string, FieldNode>;
  trail: string[];
  /** Original-question context for trail positions; absent entries mean none. */
  trail_contexts?: Record<string, string>;
}

export interface SessionStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

type EvidencePaper = Paper & { referenced_works?: string[] };

const MODES: readonly Mode[] = ["auto", "demo", "live"];
const PAPER_SOURCES: readonly PaperSource[] = ["openalex", "demo"];
const ANALYSIS_SOURCES: readonly AnalysisSource[] = ["llm", "mock", "pending"];
const PHASES = ["papers", "map", "complete"] as const;
const EVIDENCE_STATUSES: readonly EvidenceStatus[] = [
  "supported",
  "weak",
  "unverified",
];
const CLAIM_LEVELS: readonly ClaimLevel[] = [
  "research_direction",
  "theory_or_proposed",
  "title_only",
];
const EVIDENCE_QUOTE_SOURCES: readonly EvidenceQuoteSource[] = [
  "abstract",
  "title",
];
const CORE_BASES: readonly CorePaperBasis[] = [
  "abstract",
  "title",
  "unverified",
];
const CORE_ROLES: readonly CorePaperRole[] = [
  "primary",
  "review",
  "background",
  "non_research",
  "unknown",
];

// Keep the storage module dependency-free so it can be loaded directly by
// browser tooling and Node's type-strip test runner. This mirrors the public
// exploration requestKey normalization contract exactly.
function normalizeField(name: string): string {
  const value = name
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[‐‑‒–—−_]/g, "-")
    .replace(/\s*-\s*/g, "-")
    .trim()
    .replace(/\s+/g, " ");
  const aliases: Record<string, string> = {
    nhse: "non-hermitian skin effect",
    非厄米趋肤效应: "non-hermitian skin effect",
    "non hermitian skin effect": "non-hermitian skin effect",
    "incoherent non-hermitian skin effect": "incoherent nhse",
  };
  return aliases[value] || value;
}

function normalizeResearchQuestion(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const normalized = value.normalize("NFKC").replace(/\s+/g, " ").trim();
  return normalized ? normalized.slice(0, 1000) : undefined;
}

const requestKey = (
  name: string,
  mode: Mode,
  researchQuestion?: string | null,
) => {
  const base = `${mode}:${normalizeField(name)}`;
  const question = normalizeResearchQuestion(researchQuestion);
  return question ? `${base}:q:${encodeURIComponent(question)}` : base;
};

const blankSession = (): Session => ({
  history: [],
  current: "",
  mode: "auto",
  snapshots: {},
  trail: [],
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMode(value: unknown): value is Mode {
  return typeof value === "string" && MODES.includes(value as Mode);
}

function modeOr(value: unknown, fallback: Mode): Mode {
  return isMode(value) ? value : fallback;
}

function finiteNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function numberOrZero(value: unknown): number {
  const number = finiteNumberOrNull(value);
  return number === null ? 0 : Math.max(0, number);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function uniqueStrings(value: unknown): string[] {
  return [...new Set(stringList(value))];
}

function sanitizePaper(value: unknown): EvidencePaper | null {
  if (!isRecord(value)) return null;
  if (typeof value.id !== "string" || typeof value.title !== "string")
    return null;
  const paper: EvidencePaper = {
    id: value.id,
    title: value.title,
    year: finiteNumberOrNull(value.year),
    authors: stringList(value.authors),
    citation_count: finiteNumberOrNull(value.citation_count),
    doi: typeof value.doi === "string" ? value.doi : null,
    url: typeof value.url === "string" ? value.url : null,
    journal: typeof value.journal === "string" ? value.journal : null,
    source: typeof value.source === "string" ? value.source : "openalex",
  };
  if (typeof value.abstract === "string" || value.abstract === null)
    paper.abstract = value.abstract;
  if (Array.isArray(value.referenced_works))
    paper.referenced_works = uniqueStrings(value.referenced_works);
  if (typeof value.work_type === "string" || value.work_type === null)
    paper.work_type = value.work_type;
  if (typeof value.work_version === "string" || value.work_version === null)
    paper.work_version = value.work_version;
  if (Array.isArray(value.source_record_ids))
    paper.source_record_ids = uniqueStrings(value.source_record_ids);
  if (
    typeof value.abstract_source_record_id === "string" ||
    value.abstract_source_record_id === null
  )
    paper.abstract_source_record_id = value.abstract_source_record_id;
  if (typeof value.is_retracted === "boolean")
    paper.is_retracted = value.is_retracted;
  if (typeof value.is_paratext === "boolean")
    paper.is_paratext = value.is_paratext;
  return paper;
}

function sanitizeEvidenceQuotes(value: unknown): EvidenceQuote[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((quote) => {
      const source = EVIDENCE_QUOTE_SOURCES.includes(
        quote.source as EvidenceQuoteSource,
      )
        ? (quote.source as EvidenceQuoteSource)
        : null;
      const paperId = typeof quote.paper_id === "string" ? quote.paper_id : "";
      const text = typeof quote.quote === "string" ? quote.quote.trim() : "";
      if (!source || !paperId || !text) return null;
      return { paper_id: paperId, source, quote: text.slice(0, 600) };
    })
    .filter((quote): quote is EvidenceQuote => Boolean(quote));
}

function sanitizeRelation(value: unknown) {
  if (!isRecord(value) || typeof value.name !== "string") return null;
  const relation = {
    name: value.name,
    reason: typeof value.reason === "string" ? value.reason : "",
    confidence: Math.min(1, Math.max(0, numberOrZero(value.confidence))),
    evidence_paper_ids: uniqueStrings(value.evidence_paper_ids),
  };
  const status = EVIDENCE_STATUSES.includes(
    value.evidence_status as EvidenceStatus,
  )
    ? (value.evidence_status as EvidenceStatus)
    : undefined;
  const quotes = sanitizeEvidenceQuotes(value.evidence_quotes);
  const warnings = uniqueStrings(value.evidence_warnings).slice(0, 8);
  const claimLevel = CLAIM_LEVELS.includes(value.claim_level as ClaimLevel)
    ? (value.claim_level as ClaimLevel)
    : "research_direction";
  return {
    ...relation,
    claim_level: claimLevel,
    ...(status ? { evidence_status: status } : {}),
    ...(quotes.length ? { evidence_quotes: quotes } : {}),
    ...(warnings.length ? { evidence_warnings: warnings } : {}),
  };
}

function sanitizeCorePaper(value: unknown) {
  if (!isRecord(value)) return null;
  const paper = sanitizePaper(value.paper);
  if (!paper) return null;
  const signals: Record<string, number> = {};
  if (isRecord(value.signals)) {
    for (const [key, signal] of Object.entries(value.signals)) {
      const number = finiteNumberOrNull(signal);
      if (number !== null) signals[key] = number;
    }
  }
  const basis = CORE_BASES.includes(value.evidence_basis as CorePaperBasis)
    ? (value.evidence_basis as CorePaperBasis)
    : undefined;
  const role = CORE_ROLES.includes(value.role as CorePaperRole)
    ? (value.role as CorePaperRole)
    : undefined;
  const quote =
    typeof value.evidence_quote === "string"
      ? value.evidence_quote.trim().slice(0, 600)
      : value.evidence_quote === null
        ? null
        : undefined;
  return {
    paper,
    score: Math.min(1, Math.max(0, numberOrZero(value.score))),
    reason: typeof value.reason === "string" ? value.reason : "",
    signals,
    ...(basis ? { evidence_basis: basis } : {}),
    ...(quote !== undefined ? { evidence_quote: quote } : {}),
    ...(role ? { role } : {}),
  };
}

/**
 * Copy only the public FieldNode contract. This is also used by export code,
 * and intentionally drops arbitrary fields such as provider/API metadata.
 */
export function sanitizeFieldNode(value: unknown): FieldNode | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.summary !== "string" ||
    !Array.isArray(value.prerequisites) ||
    !Array.isArray(value.subfields) ||
    !Array.isArray(value.core_papers) ||
    !PAPER_SOURCES.includes(value.paper_source as PaperSource) ||
    !ANALYSIS_SOURCES.includes(value.analysis_source as AnalysisSource) ||
    !PHASES.includes(value.phase as (typeof PHASES)[number])
  )
    return null;

  const prerequisites = value.prerequisites
    .map(sanitizeRelation)
    .filter((item): item is NonNullable<ReturnType<typeof sanitizeRelation>> =>
      Boolean(item),
    );
  const subfields = value.subfields
    .map(sanitizeRelation)
    .filter((item): item is NonNullable<ReturnType<typeof sanitizeRelation>> =>
      Boolean(item),
    );
  const corePapers = value.core_papers
    .map(sanitizeCorePaper)
    .filter((item): item is NonNullable<ReturnType<typeof sanitizeCorePaper>> =>
      Boolean(item),
    );
  const evidencePapers = Array.isArray(value.evidence_papers)
    ? value.evidence_papers
        .map(sanitizePaper)
        .filter((item): item is EvidencePaper => Boolean(item))
    : [];

  const analyzed =
    value.analyzed_paper_count === null
      ? null
      : finiteNumberOrNull(value.analyzed_paper_count);

  const field: FieldNode = {
    id: value.id,
    name: value.name,
    summary: value.summary,
    prerequisites,
    subfields,
    core_papers: corePapers,
    paper_source: value.paper_source as PaperSource,
    analysis_source: value.analysis_source as AnalysisSource,
    phase: value.phase as FieldNode["phase"],
    candidate_count: Math.floor(numberOrZero(value.candidate_count)),
    analyzed_paper_count: analyzed,
    warnings: stringList(value.warnings),
    created_at: typeof value.created_at === "string" ? value.created_at : "",
    cache_hit: value.cache_hit === true,
    quality_revision:
      typeof value.quality_revision === "number" &&
      Number.isFinite(value.quality_revision)
        ? Math.max(0, Math.floor(value.quality_revision))
        : 0,
    research_question:
      normalizeResearchQuestion(value.research_question) ?? null,
  };
  field.evidence_papers = evidencePapers;
  return field;
}

function sanitizeHistoryEntry(
  value: unknown,
  fallbackMode: Mode,
): HistoryEntry | null {
  if (!isRecord(value) || typeof value.name !== "string") return null;
  const name = value.name.trim();
  if (!name) return null;
  const entry: HistoryEntry = {
    name,
    parent:
      typeof value.parent === "string" && value.parent.trim()
        ? value.parent
        : null,
    mode: modeOr(value.mode, fallbackMode),
  };
  const researchQuestion = normalizeResearchQuestion(value.research_question);
  if (researchQuestion) entry.research_question = researchQuestion;
  if (typeof value.created_at === "string") entry.created_at = value.created_at;
  if (PAPER_SOURCES.includes(value.paper_source as PaperSource))
    entry.paper_source = value.paper_source as PaperSource;
  if (ANALYSIS_SOURCES.includes(value.analysis_source as AnalysisSource))
    entry.analysis_source = value.analysis_source as AnalysisSource;
  return entry;
}

function sanitizeHistory(value: unknown, fallbackMode: Mode): HistoryEntry[] {
  if (!Array.isArray(value)) return [];
  const entries = new Map<string, HistoryEntry>();
  for (const item of value) {
    const entry = sanitizeHistoryEntry(item, fallbackMode);
    if (!entry) continue;
    entries.set(
      requestKey(entry.name, entry.mode, entry.research_question),
      entry,
    );
  }
  return [...entries.values()].slice(-50);
}

function parseSnapshotMode(key: string): Mode | null {
  const separator = key.indexOf(":");
  if (separator <= 0) return null;
  const mode = key.slice(0, separator);
  return isMode(mode) ? mode : null;
}

function sanitizeSnapshots(value: unknown): Record<string, FieldNode> {
  if (!isRecord(value)) return {};
  const snapshots = new Map<string, FieldNode>();
  for (const [rawKey, rawField] of Object.entries(value)) {
    const mode = parseSnapshotMode(rawKey);
    if (!mode) continue;
    const field = sanitizeFieldNode(rawField);
    if (!field || field.phase !== "complete") continue;
    // A live/automatic snapshot created before the evidence audit must not
    // shadow a fresh backend result. Keep demo snapshots readable for offline
    // use, while requiring the current quality contract for live data.
    if (
      mode !== "demo" &&
      (field.quality_revision ?? 0) < CURRENT_QUALITY_REVISION
    )
      continue;
    snapshots.set(requestKey(field.name, mode, field.research_question), field);
  }
  return Object.fromEntries([...snapshots.entries()].slice(-8));
}

function sanitizeTrail(value: unknown): string[] {
  return stringList(value)
    .filter((item) => item.trim())
    .slice(-50);
}

function sanitizeTrailContexts(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  const contexts: Record<string, string> = {};
  for (const [key, rawQuestion] of Object.entries(value)) {
    if (!/^\d+$/.test(key)) continue;
    const question = normalizeResearchQuestion(rawQuestion);
    if (question) contexts[key] = question;
  }
  return contexts;
}

function normalizeSessionRecord(
  value: unknown,
  fallbackMode: Mode,
): Session | null {
  if (!isRecord(value)) return null;
  if (value.history !== undefined && !Array.isArray(value.history)) return null;
  const mode = modeOr(value.mode, fallbackMode);
  const trailContexts = sanitizeTrailContexts(value.trail_contexts);
  return {
    history: sanitizeHistory(value.history, mode),
    current: typeof value.current === "string" ? value.current : "",
    ...(normalizeResearchQuestion(value.current_research_question)
      ? {
          current_research_question: normalizeResearchQuestion(
            value.current_research_question,
          ),
        }
      : {}),
    mode,
    snapshots: sanitizeSnapshots(value.snapshots),
    trail: sanitizeTrail(value.trail),
    ...(Object.keys(trailContexts).length
      ? { trail_contexts: trailContexts }
      : {}),
  };
}

function resolveStorage(storage?: SessionStorage): SessionStorage | null {
  if (storage) return storage;
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    // Access to browser storage may be denied by privacy settings.
  }
  return null;
}

function readJson(storage: SessionStorage, key: string): unknown | null {
  try {
    const text = storage.getItem(key);
    return text === null ? null : JSON.parse(text);
  } catch {
    return null;
  }
}

export function loadSession(storage?: SessionStorage): Session {
  const resolved = resolveStorage(storage);
  if (!resolved) return blankSession();

  const current = readJson(resolved, SESSION_STORAGE_KEY);
  const currentSession = normalizeSessionRecord(
    current,
    isRecord(current) && isMode(current.mode) ? current.mode : "auto",
  );
  if (currentSession) return currentSession;

  const legacy = readJson(resolved, LEGACY_SESSION_STORAGE_KEY);
  const legacyMode =
    isRecord(legacy) && isMode(legacy.mode) ? legacy.mode : "auto";
  const migrated = normalizeSessionRecord(legacy, legacyMode);
  return migrated ? { ...migrated, snapshots: {}, trail: [] } : blankSession();
}

export function saveSession(
  session: Session,
  storage?: SessionStorage,
): boolean {
  const resolved = resolveStorage(storage);
  if (!resolved) return false;

  const candidate: Record<string, unknown> = isRecord(session) ? session : {};
  const mode = modeOr(candidate.mode, "auto");
  const normalized =
    normalizeSessionRecord(
      {
        history: candidate.history,
        current: candidate.current,
        current_research_question: candidate.current_research_question,
        mode,
        snapshots: candidate.snapshots,
        trail: candidate.trail,
        trail_contexts: candidate.trail_contexts,
      },
      mode,
    ) ?? blankSession();
  const payload = JSON.stringify({ version: 2, ...normalized });
  try {
    resolved.setItem(SESSION_STORAGE_KEY, payload);
  } catch {
    return false;
  }
  try {
    resolved.removeItem(LEGACY_SESSION_STORAGE_KEY);
  } catch {
    // A successfully written v2 session is still usable if legacy cleanup fails.
  }
  return true;
}

export function clearSession(storage?: SessionStorage): boolean {
  const resolved = resolveStorage(storage);
  if (!resolved) return false;
  try {
    resolved.removeItem(SESSION_STORAGE_KEY);
    resolved.removeItem(LEGACY_SESSION_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

// Kept as a named helper for callers that want to construct snapshots without
// duplicating the mode/normalization contract.
export const sessionSnapshotKey = requestKey;
