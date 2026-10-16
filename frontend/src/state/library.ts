import type { CorePaper, Language, Paper } from "../types/index.ts";
import { exportDate, exportLabels } from "../locales/exports.ts";

export const LIBRARY_STORAGE_KEY = "field-navigator-reading-library-v1";
export const MAX_LIBRARY_ITEMS = 100;
export const MAX_NOTE_LENGTH = 4000;

export interface SavedPaper {
  /** Canonical DOI key when available, otherwise the paper id. */
  id: string;
  paper: Paper;
  /** Fields are retained when the same DOI is saved from several explorations. */
  fields: string[];
  /** May contain one labelled recommendation per source field. */
  reason: string;
  status: "to-read" | "read";
  note: string;
  saved_at: string;
}

export interface SavedPaperPatch {
  status?: SavedPaper["status"];
  note?: string;
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function nowIso(): string {
  return new Date().toISOString();
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function normalizedText(value: string): string {
  return value.trim().toLowerCase();
}

export function normalizeDoi(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .trim()
    .toLowerCase()
    .replace(/^doi:\s*/i, "")
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
    .replace(/[\s]+/g, "")
    .replace(/[.,;:)\]]+$/g, "");
}

export function normalizePaperId(value: string | null | undefined): string {
  return value ? normalizedText(value) : "";
}

type PaperIdentity = Pick<Paper, "id" | "doi"> &
  Partial<Pick<Paper, "source_record_ids" | "abstract_source_record_id">>;

function normalizedIdentityVariants(
  value: string | null | undefined,
): string[] {
  const normalized = normalizePaperId(value);
  if (!normalized) return [];
  const variants = [normalized];
  const openAlexId = normalized
    .replace(/^https?:\/\/(?:www\.)?openalex\.org\//i, "")
    .replace(/^openalex:/i, "");
  if (openAlexId && openAlexId !== normalized) variants.push(openAlexId);
  return unique(variants);
}

/** Only external HTTP(S) links may be retained or exported. */
export function safeHttpUrl(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  try {
    const parsed = new URL(value);
    if (
      (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password
    )
      return undefined;
    return parsed.href;
  } catch {
    return undefined;
  }
}

export function paperIdentityKeys(paper: PaperIdentity): string[] {
  const keys: string[] = [];
  const doi = normalizeDoi(paper.doi);
  if (doi) keys.push(`doi:${doi}`);
  const identifiers = [
    paper.id,
    ...(paper.source_record_ids ?? []),
    paper.abstract_source_record_id,
  ];
  for (const identifier of identifiers) {
    for (const variant of normalizedIdentityVariants(identifier)) {
      keys.push(`id:${variant}`);
    }
  }
  return unique(keys);
}

export function savedPaperKey(paper: PaperIdentity): string {
  return paperIdentityKeys(paper)[0] ?? "id:unknown";
}

function recordIdentityKeys(item: SavedPaper): string[] {
  return paperIdentityKeys(item.paper);
}

export function isSavedPaper(
  paper: PaperIdentity,
  savedIds: string[] = [],
): boolean {
  const available = new Set(
    savedIds.map((value) => value.trim().toLowerCase()),
  );
  return paperIdentityKeys(paper).some(
    (key) =>
      available.has(key) || available.has(key.slice(key.indexOf(":") + 1)),
  );
}

export function getSavedPaperIds(items: SavedPaper[]): string[] {
  return unique(
    items.flatMap((item) => [
      item.id,
      ...paperIdentityKeys(item.paper),
      item.paper.id,
      ...(item.paper.source_record_ids ?? []),
      item.paper.abstract_source_record_id ?? "",
    ]),
  );
}

function safeString(value: unknown, maxLength = 100_000): string {
  return typeof value === "string" ? value.slice(0, maxLength) : "";
}

function safeYear(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function safePaper(value: unknown): Paper | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const id = safeString(raw.id, 500).trim();
  const title = safeString(raw.title, 2_000).trim();
  if (!id || !title) return null;
  const authors = Array.isArray(raw.authors)
    ? unique(
        raw.authors
          .filter((author): author is string => typeof author === "string")
          .map((author) => author.slice(0, 300).trim()),
      )
    : [];
  const citationCount =
    typeof raw.citation_count === "number" &&
    Number.isFinite(raw.citation_count)
      ? raw.citation_count
      : null;
  const doi = normalizeDoi(typeof raw.doi === "string" ? raw.doi : "");
  const url = safeHttpUrl(typeof raw.url === "string" ? raw.url : "");
  const abstract = safeString(raw.abstract, 100_000).trim();
  const workType =
    typeof raw.work_type === "string"
      ? raw.work_type.slice(0, 120).trim()
      : raw.work_type === null
        ? null
        : undefined;
  const workVersion =
    typeof raw.work_version === "string"
      ? raw.work_version.slice(0, 120).trim()
      : raw.work_version === null
        ? null
        : undefined;
  const sourceRecordIds = Array.isArray(raw.source_record_ids)
    ? unique(
        raw.source_record_ids
          .filter((item): item is string => typeof item === "string")
          .map((item) => item.slice(0, 500).trim()),
      ).slice(0, 32)
    : [];
  const abstractSourceRecordId =
    typeof raw.abstract_source_record_id === "string"
      ? raw.abstract_source_record_id.slice(0, 500).trim() || null
      : raw.abstract_source_record_id === null
        ? null
        : undefined;
  return {
    id,
    title,
    year: safeYear(raw.year),
    authors,
    citation_count: citationCount,
    doi: doi || null,
    url: url ?? null,
    journal: safeString(raw.journal, 500) || null,
    source: safeString(raw.source, 100) || "openalex",
    ...(abstract ? { abstract } : {}),
    ...(workType !== undefined ? { work_type: workType || null } : {}),
    ...(workVersion !== undefined ? { work_version: workVersion || null } : {}),
    ...(sourceRecordIds.length ? { source_record_ids: sourceRecordIds } : {}),
    ...(abstractSourceRecordId !== undefined
      ? { abstract_source_record_id: abstractSourceRecordId }
      : {}),
    ...(typeof raw.is_retracted === "boolean"
      ? { is_retracted: raw.is_retracted }
      : {}),
    ...(typeof raw.is_paratext === "boolean"
      ? { is_paratext: raw.is_paratext }
      : {}),
  } as Paper;
}

export function sanitizeSavedPaper(value: unknown): SavedPaper | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const paper = safePaper(raw.paper);
  if (!paper) return null;
  const fields = Array.isArray(raw.fields)
    ? unique(
        raw.fields
          .filter((field): field is string => typeof field === "string")
          .map((field) => field.slice(0, 300).trim()),
      )
    : [];
  const savedAt = safeString(raw.saved_at, 80) || nowIso();
  return {
    id: savedPaperKey(paper),
    paper,
    fields,
    reason: safeString(raw.reason, 16_000),
    status: raw.status === "read" ? "read" : "to-read",
    note: safeString(raw.note, MAX_NOTE_LENGTH),
    saved_at: savedAt,
  };
}

function mergeReasons(first: string, second: string): string {
  if (!first) return second;
  if (!second || first.includes(second)) return first;
  return `${first}\n${second}`;
}

function officialMetadataRecordId(value: string | null | undefined): boolean {
  if (!value) return false;
  try {
    const record = new URL(value);
    if (
      (record.hostname === "arxiv.org" &&
        record.pathname.startsWith("/abs/") &&
        !record.search &&
        !record.hash) ||
      (record.hostname === "api.datacite.org" &&
        record.pathname.startsWith("/dois/") &&
        !record.search &&
        !record.hash) ||
      (record.hostname === "doi.org" &&
        record.pathname.toLowerCase().startsWith("/10.48550/arxiv.") &&
        !record.search &&
        !record.hash)
    ) {
      return true;
    }
  } catch {
    // An index alias is not sufficient evidence of official metadata.
  }
  return false;
}

function normalizedWorkVersion(paper: Paper): string {
  return normalizedText(paper.work_version ?? "").replace(/[\s_-]+/g, "");
}

function isArxivAbstractUrl(value: string | null | undefined): boolean {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    if (
      (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      parsed.hostname !== "arxiv.org" ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.search ||
      parsed.hash
    ) {
      return false;
    }
    return /^\/abs\/(?:\d{4}\.\d{4,5}|[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)?\/\d{7})(?:v\d+)?$/i.test(
      parsed.pathname,
    );
  } catch {
    return false;
  }
}

function arxivIdentifier(
  value: string | null | undefined,
): [string, string | null] | null {
  if (!value) return null;
  const match = value
    .trim()
    .match(
      /(?:arxiv(?:\.org)?\/(?:abs\/)?|arxiv:|arxiv\.|10\.48550\/arxiv[.:])([0-9]{4}\.[0-9]{4,5})(?:v([0-9]+))?/i,
    );
  return match ? [match[1].toLowerCase(), match[2] ?? null] : null;
}

function officialRecordIsAssociated(paper: Paper, recordId: string): boolean {
  const normalizedRecord = normalizePaperId(recordId);
  const aliases = [
    paper.doi ?? "",
    paper.url ?? "",
    paper.id,
    ...(paper.source_record_ids ?? []),
  ];
  if (aliases.some((alias) => normalizePaperId(alias) === normalizedRecord)) {
    return true;
  }
  const recordArxiv = arxivIdentifier(recordId);
  return Boolean(
    recordArxiv &&
    aliases.some((alias) => arxivIdentifier(alias)?.[0] === recordArxiv[0]),
  );
}

function hasVerifiedMetadata(paper: Paper): boolean {
  const recordId = paper.abstract_source_record_id;
  if (typeof recordId !== "string" || !officialMetadataRecordId(recordId)) {
    return false;
  }
  const source = normalizedText(paper.source);
  return (
    source === "arxiv" ||
    source === "datacite" ||
    officialRecordIsAssociated(paper, recordId)
  );
}

function isPreprintPaper(paper: Paper): boolean {
  const source = normalizedText(paper.source);
  const type = normalizedText(paper.work_type ?? "");
  const version = normalizedWorkVersion(paper);
  const doi = normalizeDoi(paper.doi);
  const arxivDoi = doi.startsWith("10.48550/arxiv.");
  const publisherDoi = Boolean(doi && !arxivDoi);
  // Match the backend verifier: an arXiv DOI remains a preprint signal even
  // when an older OpenAlex record incorrectly labels its work version as
  // publishedVersion.
  if (
    arxivDoi ||
    source === "arxiv" ||
    source === "datacite" ||
    type === "preprint" ||
    version === "preprint" ||
    version === "submittedversion"
  ) {
    return true;
  }
  // A sparse OpenAlex article can expose only its arXiv abstract URL.  Treat
  // that URL as a preprint signal unless a publisher DOI identifies the
  // record; source_record_ids alone remain aliases and do not reclassify a
  // publisher record.
  if (isArxivAbstractUrl(paper.url) && !publisherDoi) return true;
  if (
    version === "published" ||
    version === "publishedversion" ||
    version === "accepted" ||
    version === "acceptedversion" ||
    version === "versionofrecord"
  ) {
    return false;
  }
  // source_record_ids can retain a preprint alias for a published work.  An
  // alias alone is not enough to reclassify a paper as a preprint.
  return false;
}

function isPublishedPaper(paper: Paper): boolean {
  if (isPreprintPaper(paper)) return false;
  const type = normalizedText(paper.work_type ?? "");
  const version = normalizedWorkVersion(paper);
  if (
    version === "published" ||
    version === "publishedversion" ||
    version === "accepted" ||
    version === "acceptedversion" ||
    version === "versionofrecord"
  ) {
    return true;
  }
  const doi = normalizeDoi(paper.doi);
  if (doi && !doi.startsWith("10.48550/arxiv.")) return true;
  // OpenAlex may omit both DOI and location.version for a normal article.
  // The article type is a publisher signal only after the arXiv signals above
  // have been ruled out.
  return type === "article";
}

function titlesDiffer(first: Paper, second: Paper): boolean {
  return normalizedText(first.title) !== normalizedText(second.title);
}

interface PaperMergeChoice {
  preferred: Paper;
  fallback: Paper;
  preferredIsFirst: boolean;
  publishedProtection: boolean;
}

function chooseCanonicalPaper(first: Paper, second: Paper): PaperMergeChoice {
  const firstPreprint = isPreprintPaper(first);
  const secondPreprint = isPreprintPaper(second);
  const firstPublished = isPublishedPaper(first);
  const secondPublished = isPublishedPaper(second);

  // A published record remains canonical whenever its identity is merged with
  // a preprint.  A conflicting title also blocks fallback of semantic fields
  // from the preprint, regardless of which record carries an official abstract.
  if (firstPublished && secondPreprint) {
    return {
      preferred: first,
      fallback: second,
      preferredIsFirst: true,
      publishedProtection: titlesDiffer(first, second),
    };
  }
  if (secondPublished && firstPreprint) {
    return {
      preferred: second,
      fallback: first,
      preferredIsFirst: false,
      publishedProtection: titlesDiffer(first, second),
    };
  }

  const firstVerified = hasVerifiedMetadata(first);
  const secondVerified = hasVerifiedMetadata(second);
  if (firstVerified !== secondVerified) {
    return secondVerified
      ? {
          preferred: second,
          fallback: first,
          preferredIsFirst: false,
          publishedProtection: false,
        }
      : {
          preferred: first,
          fallback: second,
          preferredIsFirst: true,
          publishedProtection: false,
        };
  }

  // For two independently verified records, retain the existing canonical
  // record unless the later one supplies a clear title correction.
  if (firstVerified && secondVerified && titlesDiffer(first, second)) {
    return {
      preferred: second,
      fallback: first,
      preferredIsFirst: false,
      publishedProtection: false,
    };
  }
  return {
    preferred: first,
    fallback: second,
    preferredIsFirst: true,
    publishedProtection: false,
  };
}

function mergePaper(first: Paper, second: Paper): Paper {
  const choice = chooseCanonicalPaper(first, second);
  const canonical = choice.preferred;
  const fallback = choice.fallback;
  const preserveCanonicalFields =
    choice.publishedProtection || hasVerifiedMetadata(canonical);
  const authors = preserveCanonicalFields
    ? canonical.authors
    : canonical.authors.length
      ? canonical.authors
      : fallback.authors;
  const year = preserveCanonicalFields
    ? canonical.year
    : (canonical.year ?? fallback.year);
  const doi = preserveCanonicalFields
    ? canonical.doi
    : canonical.doi || fallback.doi;
  const url = preserveCanonicalFields
    ? canonical.url
    : canonical.url || fallback.url;
  const journal = preserveCanonicalFields
    ? canonical.journal
    : canonical.journal || fallback.journal;
  const abstract = preserveCanonicalFields
    ? canonical.abstract
    : canonical.abstract || fallback.abstract;
  const workType = preserveCanonicalFields
    ? canonical.work_type
    : (canonical.work_type ?? fallback.work_type);
  const workVersion = preserveCanonicalFields
    ? canonical.work_version
    : (canonical.work_version ?? fallback.work_version);
  const abstractSourceRecordId = preserveCanonicalFields
    ? canonical.abstract_source_record_id
    : (canonical.abstract_source_record_id ??
      fallback.abstract_source_record_id);
  const sourceRecordIds = unique([
    ...(first.source_record_ids ?? []),
    ...(second.source_record_ids ?? []),
  ]);
  const isRetracted =
    first.is_retracted === true || second.is_retracted === true
      ? true
      : (first.is_retracted ?? second.is_retracted);
  const isParatext =
    first.is_paratext === true || second.is_paratext === true
      ? true
      : (first.is_paratext ?? second.is_paratext);
  return {
    ...canonical,
    title: canonical.title || fallback.title,
    authors,
    year,
    // Citation counts belong to the chosen record.  Never synthesize one by
    // carrying it across a correction, source, or work-version merge.
    citation_count: canonical.citation_count,
    doi,
    url,
    journal,
    source: canonical.source || fallback.source,
    ...(abstract ? { abstract } : {}),
    ...(workType !== undefined ? { work_type: workType } : {}),
    ...(workVersion !== undefined ? { work_version: workVersion } : {}),
    ...(sourceRecordIds.length ? { source_record_ids: sourceRecordIds } : {}),
    ...(abstractSourceRecordId !== undefined
      ? { abstract_source_record_id: abstractSourceRecordId }
      : {}),
    ...(isRetracted !== undefined ? { is_retracted: isRetracted } : {}),
    ...(isParatext !== undefined ? { is_paratext: isParatext } : {}),
  } as Paper;
}

export function mergeSavedPapers(
  first: SavedPaper,
  second: SavedPaper,
): SavedPaper {
  const choice = chooseCanonicalPaper(first.paper, second.paper);
  const verifiedTitleCorrection =
    titlesDiffer(first.paper, second.paper) &&
    (hasVerifiedMetadata(first.paper) || hasVerifiedMetadata(second.paper));
  const canonicalReason = choice.preferredIsFirst
    ? first.reason
    : second.reason;
  return {
    ...first,
    id: savedPaperKey(mergePaper(first.paper, second.paper)),
    paper: mergePaper(first.paper, second.paper),
    fields: unique([...first.fields, ...second.fields]),
    // A rejected preprint or an official title correction must not leave the
    // old automatic explanation attached to the new canonical identity.
    reason:
      choice.publishedProtection || verifiedTitleCorrection
        ? canonicalReason
        : mergeReasons(first.reason, second.reason),
    status:
      first.status === "read" || second.status === "read" ? "read" : "to-read",
    note: first.note || second.note,
    saved_at: first.saved_at || second.saved_at,
  };
}

function findMatchingIndex(items: SavedPaper[], candidate: SavedPaper): number {
  const keys = new Set(recordIdentityKeys(candidate));
  return items.findIndex((item) =>
    recordIdentityKeys(item).some((key) => keys.has(key)),
  );
}

export function normalizeLibrary(value: unknown): SavedPaper[] {
  const rawItems = Array.isArray(value) ? value : [];
  const normalized: SavedPaper[] = [];
  for (const raw of rawItems) {
    const item = sanitizeSavedPaper(raw);
    if (!item) continue;
    const index = findMatchingIndex(normalized, item);
    if (index >= 0)
      normalized[index] = mergeSavedPapers(normalized[index], item);
    else normalized.push(item);
  }
  return normalized.slice(0, MAX_LIBRARY_ITEMS);
}

function createSavedPaper(core: CorePaper, fieldName: string): SavedPaper {
  const paper = safePaper(core.paper) ?? core.paper;
  const field = fieldName.trim() || "未命名领域";
  return {
    id: savedPaperKey(paper),
    paper,
    fields: [field],
    reason: `${field}：${core.reason}`,
    status: "to-read",
    note: "",
    saved_at: nowIso(),
  };
}

/** Add or merge a paper and cap new records at MAX_LIBRARY_ITEMS. */
export function addToLibrary(
  items: SavedPaper[],
  core: CorePaper,
  fieldName: string,
): SavedPaper[] {
  const normalizedItems = normalizeLibrary(items);
  const candidate = createSavedPaper(core, fieldName);
  const index = findMatchingIndex(normalizedItems, candidate);
  if (index >= 0) {
    const next = normalizedItems.slice();
    next[index] = mergeSavedPapers(next[index], candidate);
    return next;
  }
  // At capacity, reject only this new record. Never prepend then slice, which
  // would silently evict the user's oldest saved paper.
  if (normalizedItems.length >= MAX_LIBRARY_ITEMS) return normalizedItems;
  return [candidate, ...normalizedItems];
}

export function updateLibraryItem(
  items: SavedPaper[],
  id: string,
  patch: SavedPaperPatch,
): SavedPaper[] {
  return items.map((item) =>
    item.id !== id
      ? item
      : {
          ...item,
          ...(patch.status === "read" || patch.status === "to-read"
            ? { status: patch.status }
            : {}),
          ...(typeof patch.note === "string"
            ? { note: patch.note.slice(0, MAX_NOTE_LENGTH) }
            : {}),
        },
  );
}

export function removeLibraryItem(
  items: SavedPaper[],
  id: string,
): SavedPaper[] {
  return items.filter((item) => item.id !== id);
}

/** Undo a local removal without replacing a newer copy or evicting another paper. */
export function restoreLibraryItem(
  items: SavedPaper[],
  removed: SavedPaper,
  originalIndex = 0,
): SavedPaper[] {
  if (
    items.length >= MAX_LIBRARY_ITEMS ||
    isSavedPaper(removed.paper, getSavedPaperIds(items))
  )
    return items;
  const index = Number.isFinite(originalIndex)
    ? Math.min(items.length, Math.max(0, Math.trunc(originalIndex)))
    : 0;
  return [...items.slice(0, index), removed, ...items.slice(index)];
}

export function clearLibrary(): SavedPaper[] {
  return [];
}

function getStorage(storage?: StorageLike | null): StorageLike | null {
  if (storage !== undefined) return storage;
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Load malformed or unavailable storage as an empty list without throwing. */
export function loadLibrary(storage?: Storage): SavedPaper[] {
  const target = getStorage(storage);
  if (!target) return [];
  try {
    const raw = target.getItem(LIBRARY_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    const value =
      parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as { items?: unknown }).items
        : parsed;
    return Array.isArray(value) ? normalizeLibrary(value) : [];
  } catch {
    return [];
  }
}

/** Return false on quota/security errors so the root can show a visible notice. */
export function saveLibrary(items: SavedPaper[], storage?: Storage): boolean {
  const target = getStorage(storage);
  if (!target) return false;
  try {
    target.setItem(
      LIBRARY_STORAGE_KEY,
      JSON.stringify({ version: 1, items: normalizeLibrary(items) }),
    );
    return true;
  } catch {
    return false;
  }
}

function oneLine(value: string): string {
  return value
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeMarkdown(value: string): string {
  return value
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\\/g, "\\\\")
    .replace(/([`*_[\]{}()#+.!|>~-])/g, "\\$1");
}

function markdownUrl(value: string): string {
  return value.replace(/[()\\\s]/g, (character) =>
    encodeURIComponent(character),
  );
}

/** Export paper metadata and notes only; no model settings or network calls. */
export function exportLibraryMarkdown(
  items: SavedPaper[],
  language: Language = "zh-CN",
): string {
  const labels = exportLabels(language);
  const labelColon = language === "en" ? ": " : "：";
  const normalized = normalizeLibrary(items);
  const lines = [
    `# ${labels.readingList}`,
    "",
    `${labels.exportedAt}${labelColon}${new Date().toISOString()}`,
    "",
  ];
  for (const [status, heading] of [
    ["to-read", labels.toRead],
    ["read", labels.read],
  ] as const) {
    const group = normalized.filter((item) => item.status === status);
    if (!group.length) continue;
    lines.push(`## ${heading}`, "");
    for (const item of group) {
      const title = escapeMarkdown(oneLine(item.paper.title));
      const url = safeHttpUrl(item.paper.url);
      lines.push(
        url ? `### [${title}](<${markdownUrl(url)}>)` : `### ${title}`,
      );
      lines.push(
        `- ${labels.authors}${labelColon}${escapeMarkdown(item.paper.authors.map(oneLine).join(", ") || (language === "en" ? "Not provided" : "未提供"))}`,
        `- ${labels.year}${labelColon}${item.paper.year ?? labels.unknown}`,
        `- ${labels.journal}${labelColon}${escapeMarkdown(oneLine(item.paper.journal || (language === "en" ? "Not provided" : "未提供")))}`,
        `- ${labels.doi}${labelColon}${item.paper.doi ? `\`${escapeMarkdown(normalizeDoi(item.paper.doi))}\`` : language === "en" ? "Not provided" : "未提供"}`,
      );
      if (item.fields.length) {
        lines.push(
          `- ${labels.fields}${labelColon}${item.fields.map((field) => escapeMarkdown(oneLine(field))).join(language === "en" ? ", " : "、")}`,
        );
      }
      if (item.reason) {
        lines.push(
          `- ${labels.reason}${labelColon}${escapeMarkdown(item.reason)}`,
        );
      }
      if (item.note) {
        lines.push(`- ${labels.note}${labelColon}`);
        for (const line of item.note.split(/\r?\n/))
          lines.push(`  > ${escapeMarkdown(line) || " "}`);
      }
      if (item.saved_at)
        lines.push(
          `- ${labels.savedAt}${labelColon}${exportDate(item.saved_at)}`,
        );
      lines.push("");
    }
  }
  if (!normalized.length) lines.push(labels.empty, "");
  return lines.join("\n");
}
