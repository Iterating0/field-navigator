import type {
  ClaimLevel,
  CorePaperBasis,
  CorePaperRole,
  EvidenceQuote,
  EvidenceQuoteSource,
  EvidenceStatus,
  FieldNode,
  Paper,
  Language,
} from "../types/index.ts";
import { exportLabels } from "../locales/exports.ts";

export const MAP_EXPORT_VERSION = 1;

type EvidencePaper = Paper & { referenced_works?: string[] };

function limitations(language: Language): string[] {
  const labels = exportLabels(language);
  return [
    labels.heuristicLimit,
    labels.confidenceLimit,
    labels.metadataLimit,
    labels.evidenceLimit,
    labels.maturityLimit,
  ];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

type SanitizedPaper = Paper & { referenced_works?: string[] };

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

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function sanitizePaper(value: unknown): SanitizedPaper | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.title !== "string"
  )
    return null;
  const paper: SanitizedPaper = {
    id: value.id,
    title: value.title,
    year: finiteNumber(value.year),
    authors: stringList(value.authors),
    citation_count: finiteNumber(value.citation_count),
    doi: typeof value.doi === "string" ? value.doi : null,
    url: typeof value.url === "string" ? value.url : null,
    journal: typeof value.journal === "string" ? value.journal : null,
    source: typeof value.source === "string" ? value.source : "openalex",
  };
  if (typeof value.abstract === "string" || value.abstract === null)
    paper.abstract = value.abstract;
  if (Array.isArray(value.referenced_works))
    paper.referenced_works = [...new Set(stringList(value.referenced_works))];
  if (typeof value.work_type === "string" || value.work_type === null)
    paper.work_type = value.work_type;
  if (typeof value.work_version === "string" || value.work_version === null)
    paper.work_version = value.work_version;
  if (Array.isArray(value.source_record_ids))
    paper.source_record_ids = [...new Set(stringList(value.source_record_ids))];
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
    .map((item) => {
      const source = EVIDENCE_QUOTE_SOURCES.includes(
        item.source as EvidenceQuoteSource,
      )
        ? (item.source as EvidenceQuoteSource)
        : null;
      const paperId = typeof item.paper_id === "string" ? item.paper_id : "";
      const quote = typeof item.quote === "string" ? item.quote.trim() : "";
      if (!source || !paperId || !quote) return null;
      return { paper_id: paperId, source, quote: quote.slice(0, 600) };
    })
    .filter((item): item is EvidenceQuote => Boolean(item));
}

function sanitizeRelation(value: unknown) {
  if (!isRecord(value) || typeof value.name !== "string") return null;
  const status = EVIDENCE_STATUSES.includes(
    value.evidence_status as EvidenceStatus,
  )
    ? (value.evidence_status as EvidenceStatus)
    : undefined;
  const quotes = sanitizeEvidenceQuotes(value.evidence_quotes);
  const warnings = [...new Set(stringList(value.evidence_warnings))].slice(
    0,
    8,
  );
  const claimLevel = CLAIM_LEVELS.includes(value.claim_level as ClaimLevel)
    ? (value.claim_level as ClaimLevel)
    : "research_direction";
  return {
    name: value.name,
    reason: typeof value.reason === "string" ? value.reason : "",
    confidence:
      typeof value.confidence === "number" && Number.isFinite(value.confidence)
        ? Math.min(1, Math.max(0, value.confidence))
        : 0,
    evidence_paper_ids: [...new Set(stringList(value.evidence_paper_ids))],
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
    for (const [name, signal] of Object.entries(value.signals)) {
      const number = finiteNumber(signal);
      if (number !== null) signals[name] = number;
    }
  }
  const score = finiteNumber(value.score);
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
    score: score === null ? 0 : Math.min(1, Math.max(0, score)),
    reason: typeof value.reason === "string" ? value.reason : "",
    signals,
    ...(basis ? { evidence_basis: basis } : {}),
    ...(quote !== undefined ? { evidence_quote: quote } : {}),
    ...(role ? { role } : {}),
  };
}

function sanitizeField(value: unknown): FieldNode | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.summary !== "string" ||
    !Array.isArray(value.prerequisites) ||
    !Array.isArray(value.subfields) ||
    !Array.isArray(value.core_papers) ||
    !["openalex", "demo"].includes(String(value.paper_source)) ||
    !["llm", "mock", "pending"].includes(String(value.analysis_source)) ||
    !["papers", "map", "complete"].includes(String(value.phase))
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
        .filter((item): item is SanitizedPaper => Boolean(item))
    : [];
  const analyzed =
    value.analyzed_paper_count === null
      ? null
      : finiteNumber(value.analyzed_paper_count);
  const field: FieldNode = {
    id: value.id,
    name: value.name,
    summary: value.summary,
    prerequisites,
    subfields,
    core_papers: corePapers,
    paper_source: value.paper_source as FieldNode["paper_source"],
    analysis_source: value.analysis_source as FieldNode["analysis_source"],
    phase: value.phase as FieldNode["phase"],
    candidate_count:
      typeof value.candidate_count === "number" &&
      Number.isFinite(value.candidate_count)
        ? Math.max(0, Math.floor(value.candidate_count))
        : 0,
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
      typeof value.research_question === "string"
        ? value.research_question.trim().slice(0, 1000)
        : null,
    language: value.language === "en" ? "en" : "zh-CN",
  };
  if (evidencePapers.length) field.evidence_papers = evidencePapers;
  return field;
}

/** Escape Markdown text and neutralize URL-like text in untrusted content. */
export function escapeMarkdown(value: unknown): string {
  const text = String(value ?? "")
    .replace(/\r?\n/g, " ")
    .replace(/([\\`*_{}\[\]()#+.!|<>])/g, "\\$1");
  return text.replace(/\b(https?|javascript|data):(?=\/\/)/gi, "$1\\:");
}

function escapeCode(value: unknown): string {
  return String(value ?? "").replace(/[\r\n`]/g, " ");
}

/** Allow links only to ordinary HTTP(S) sources. */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = new URL(value.trim());
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:")
      return null;
    if (/[\u0000-\u001f\u007f]/.test(parsed.href)) return null;
    return parsed.href.replace(/[<>`\\"]/g, (character) =>
      encodeURIComponent(character),
    );
  } catch {
    return null;
  }
}

function markdownLink(label: unknown, url: unknown): string {
  const safe = safeHttpUrl(url);
  if (!safe) return escapeMarkdown(label);
  return `[${escapeMarkdown(label)}](<${safe}>)`;
}

function sourceLabel(field: FieldNode, language: Language): string {
  const labels = exportLabels(language);
  const paper =
    field.paper_source === "openalex" ? "OpenAlex" : labels.demoData;
  const analysis =
    field.analysis_source === "llm"
      ? labels.llmAnalysis
      : field.analysis_source === "mock"
        ? labels.mockAnalysis
        : labels.pendingAnalysis;
  return labels.sourceSummary(paper, analysis);
}

function rangeLabel(field: FieldNode, language: Language): string {
  const labels = exportLabels(language);
  const candidate = Number.isFinite(field.candidate_count)
    ? Math.max(0, Math.floor(field.candidate_count))
    : 0;
  const analyzed =
    typeof field.analyzed_paper_count === "number" &&
    Number.isFinite(field.analyzed_paper_count)
      ? Math.max(0, Math.floor(field.analyzed_paper_count))
      : null;
  return labels.candidateRange(candidate, analyzed);
}

function confidenceLabel(value: unknown, language: Language): string {
  const labels = exportLabels(language);
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`
    : labels.unknown;
}

function evidenceStatusLabel(value: unknown, language: Language): string {
  const labels = exportLabels(language);
  if (value === "supported") return labels.supported;
  if (value === "weak") return labels.weak;
  return labels.toVerify;
}

function claimLevelLabel(value: unknown, language: Language): string {
  const labels = exportLabels(language);
  if (value === "theory_or_proposed") return labels.theoryCandidate;
  if (value === "title_only") return labels.titleOnly;
  return labels.researchDirection;
}

function evidenceBasisLabel(value: unknown, language: Language): string {
  const labels = exportLabels(language);
  if (value === "abstract") return labels.abstractEvidence;
  if (value === "title") return labels.titleClue;
  return labels.toVerify;
}

function roleLabel(value: unknown, language: Language): string {
  const labels = exportLabels(language);
  if (value === "primary") return labels.primary;
  if (value === "review") return labels.review;
  if (value === "background") return labels.background;
  if (value === "non_research") return labels.nonResearch;
  return labels.roleToVerify;
}

function relationLines(
  relations: FieldNode["prerequisites"],
  language: Language,
): string[] {
  const labels = exportLabels(language);
  if (!relations.length) return [`- ${labels.noTraceablePapers}`];
  return relations.map((relation) => {
    const evidence = relation.evidence_paper_ids?.filter(Boolean) ?? [];
    const evidenceLabel = evidence.length
      ? `；${labels.evidenceMetadata(
          evidence.map((id) => `\`${escapeCode(id)}\``).join(", "),
        )}`
      : "";
    const status = `；${labels.evidence(
      evidenceStatusLabel(relation.evidence_status, language),
    )}`;
    const claimLevel = `；${labels.maturity(
      claimLevelLabel(relation.claim_level, language),
    )}`;
    const quotes = (relation.evidence_quotes ?? [])
      .filter((item) => item.quote.trim())
      .slice(0, 2)
      .map(
        (item) =>
          `；${labels.excerpt(
            item.source === "abstract"
              ? labels.abstractEvidence
              : labels.titleClue,
            escapeMarkdown(item.quote),
          )}`,
      )
      .join("");
    return `- **${escapeMarkdown(relation.name)}** — ${escapeMarkdown(
      relation.reason,
    )}（${labels.confidence(
      confidenceLabel(relation.confidence, language),
    )}${claimLevel}${status}${evidenceLabel}${quotes}）`;
  });
}

function paperTitle(paper: Paper): string {
  return markdownLink(paper.title, paper.url);
}

function paperMetadata(paper: Paper, language: Language): string {
  const labels = exportLabels(language);
  const evidence = paper as EvidencePaper;
  const parts: string[] = [];
  if (typeof paper.year === "number" && Number.isFinite(paper.year))
    parts.push(String(Math.trunc(paper.year)));
  if (paper.journal) parts.push(escapeMarkdown(paper.journal));
  if (paper.source)
    parts.push(`${labels.source} ${escapeMarkdown(paper.source)}`);
  if (paper.id) parts.push(`id \`${escapeCode(paper.id)}\``);
  if (typeof evidence.abstract === "string")
    parts.push(labels.abstractMetadata);
  return parts.join("；") || labels.metadataIncomplete;
}

function paperLine(
  item: FieldNode["core_papers"][number],
  language: Language,
): string {
  const labels = exportLabels(language);
  const score =
    typeof item.score === "number" && Number.isFinite(item.score)
      ? `；${labels.candidateScore(
          `${Math.round(Math.min(1, Math.max(0, item.score)) * 100)}%`,
        )}`
      : "";
  const reason = item.reason ? `；${escapeMarkdown(item.reason)}` : "";
  const basis = `；${labels.evidence(
    evidenceBasisLabel(item.evidence_basis, language),
  )}`;
  const role = `；${labels.maturity(roleLabel(item.role, language))}`;
  const quote = item.evidence_quote
    ? `；${labels.excerpt(
        item.evidence_basis === "title"
          ? labels.titleClue
          : labels.abstractEvidence,
        escapeMarkdown(item.evidence_quote),
      )}`
    : "";
  return `- ${paperTitle(item.paper)} — ${paperMetadata(
    item.paper,
    language,
  )}${basis}${role}${score}${reason}${quote}`;
}

function uniquePapers(field: FieldNode): Paper[] {
  const papers = [
    ...(field.evidence_papers ?? []),
    ...field.core_papers.map((item) => item.paper),
  ];
  const seen = new Set<string>();
  return papers.filter((paper) => {
    const key = paper.id || `${paper.title}:${paper.year ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function sanitizedFields(field: FieldNode, fields?: FieldNode[]): FieldNode[] {
  const result: FieldNode[] = [];
  const seen = new Set<string>();
  for (const candidate of [field, ...(fields ?? [])]) {
    const safe = sanitizeField(candidate);
    if (!safe) continue;
    const key = safe.id || safe.name;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(safe);
  }
  return result;
}

/**
 * Build a human-readable brief for the selected field. `fields` is optional
 * context: it is listed as loaded context, while the detailed sections remain
 * about the selected field.
 */
export function buildResearchBrief(
  field: FieldNode,
  fields?: FieldNode[],
  language: Language = "zh-CN",
): string {
  const labels = exportLabels(language);
  const labelColon = language === "en" ? ": " : "：";
  const sentenceEnd = language === "en" ? "." : "。";
  const localizedLimitations = limitations(language);
  const context = sanitizedFields(field, fields);
  const current = context[0];
  if (!current) {
    return `# ${labels.product}\n\n${labels.invalidResult}`;
  }

  const lines: string[] = [
    `# ${escapeMarkdown(current.name)}`,
    "",
    `> ${labels.source}${labelColon}${sourceLabel(current, language)}${
      language === "en" ? "; " : "；"
    }${
      language === "en" ? "candidate range" : "候选范围"
    }${labelColon}${rangeLabel(current, language)}${sentenceEnd}`,
    `> ${language === "en" ? "Method limits" : "方法边界"}${labelColon}${localizedLimitations.join(" ")}`,
  ];
  if (current.research_question?.trim()) {
    lines.push(
      `> ${language === "en" ? "Original research question" : "原始研究问题"}${labelColon}${escapeMarkdown(current.research_question.trim())}`,
    );
  }
  if (current.phase !== "complete") {
    lines.push(
      `> ⚠️ ${labels.incompleteNotice.replace(
        "{phase}",
        escapeMarkdown(labels.phase(current.phase)),
      )}`,
    );
  }

  lines.push(
    "",
    `## ${labels.domainSummary}`,
    escapeMarkdown(current.summary) || labels.noSummary,
  );
  lines.push(
    "",
    `## ${labels.prerequisites}`,
    ...relationLines(current.prerequisites, language),
  );
  lines.push(
    "",
    `## ${labels.researchBranches}`,
    ...relationLines(current.subfields, language),
  );

  lines.push(
    "",
    `## ${labels.supportingCitations}`,
    `> ${labels.citationDisclaimer}`,
  );
  const supportPapers = uniquePapers(current);
  if (supportPapers.length) {
    for (const paper of supportPapers)
      lines.push(`- ${paperTitle(paper)} — ${paperMetadata(paper, language)}`);
  } else {
    lines.push(`- ${labels.noTraceablePapers}`);
  }

  const reading = current.core_papers;
  lines.push("", `## ${labels.readingStart}`);
  if (reading.length)
    lines.push(...reading.slice(0, 3).map((item) => paperLine(item, language)));
  else
    lines.push(
      `- ${language === "en" ? "No core papers were returned." : "未返回核心论文。"}`,
    );
  if (reading.length > 3) {
    lines.push(
      "",
      `## ${labels.otherCorePapers}`,
      ...reading.slice(3).map((item) => paperLine(item, language)),
    );
  }

  if (current.warnings.length) {
    lines.push(
      "",
      `## ${labels.currentLimitations}`,
      ...current.warnings.map((w) => `- ${escapeMarkdown(w)}`),
    );
  }
  if (context.length > 1) {
    lines.push("", `## ${labels.loadedFields}`);
    for (const loaded of context.slice(1))
      lines.push(
        `- **${escapeMarkdown(loaded.name)}** — ${sourceLabel(
          loaded,
          language,
        )}；${labels.phase(escapeMarkdown(loaded.phase))}。`,
      );
  }

  return lines.join("\n");
}

function exportedField(field: FieldNode) {
  const evidence = field.evidence_papers ?? [];
  return {
    id: field.id,
    name: field.name,
    summary: field.summary,
    prerequisites: field.prerequisites,
    subfields: field.subfields,
    core_papers: field.core_papers,
    paper_source: field.paper_source,
    analysis_source: field.analysis_source,
    phase: field.phase,
    candidate_count: field.candidate_count,
    analyzed_paper_count: field.analyzed_paper_count ?? null,
    warnings: field.warnings,
    created_at: field.created_at,
    evidence_papers: evidence,
    quality_revision: field.quality_revision ?? 0,
    research_question: field.research_question ?? null,
    language: field.language ?? "zh-CN",
    provenance: {
      paper_source: field.paper_source,
      analysis_source: field.analysis_source,
      candidate_count: field.candidate_count,
      analyzed_paper_count: field.analyzed_paper_count ?? null,
      phase: field.phase,
      quality_revision: field.quality_revision ?? 0,
      research_question: field.research_question ?? null,
      language: field.language ?? "zh-CN",
      limitations: limitations(field.language ?? "zh-CN"),
    },
  };
}

/**
 * Serialize a map as a portable JSON document. Only sanitized public field
 * data and evidence provenance are included; runtime/cache/config fields are
 * intentionally omitted.
 */
export function serializeMap(
  fields: FieldNode[],
  currentFieldId?: string,
  language: Language = "zh-CN",
): string {
  const localizedLimitations = limitations(language);
  const safeFields: FieldNode[] = [];
  const seen = new Set<string>();
  for (const field of Array.isArray(fields) ? fields : []) {
    const safe = sanitizeField(field);
    if (!safe) continue;
    const key = safe.id || safe.name;
    if (seen.has(key)) continue;
    seen.add(key);
    safeFields.push(safe);
  }
  const current = safeFields.find((field) => field.id === currentFieldId);
  const sourceKinds = [
    ...new Set(safeFields.map((field) => field.paper_source)),
  ];
  const analysisKinds = [
    ...new Set(safeFields.map((field) => field.analysis_source)),
  ];
  const incomplete = safeFields.some((field) => field.phase !== "complete");
  const document = {
    version: MAP_EXPORT_VERSION,
    format: "field-navigator-map",
    language,
    exported_at: new Date().toISOString(),
    current_field_id: current?.id ?? null,
    complete: safeFields.length > 0 && !incomplete,
    source: {
      product: "Field Navigator",
      paper_sources: sourceKinds,
      analysis_sources: analysisKinds,
      limitations: incomplete
        ? [
            ...localizedLimitations,
            language === "en"
              ? "Generated branches and paper judgments are not filled in when they were not returned."
              : "未生成的分支与论文判断不会在导出中补写。",
          ]
        : localizedLimitations,
    },
    fields: safeFields.map(exportedField),
  };
  return JSON.stringify(document, null, 2);
}

// Alias for callers that prefer an action-shaped name while keeping the
// canonical serializeMap signature used by the UI integration.
export const exportMap = serializeMap;
