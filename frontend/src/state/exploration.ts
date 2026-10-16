import {
  normalizeLanguage,
  type ExploreEvent,
  type FieldNode,
  type Language,
  type Mode,
} from "../types/index.ts";

function languageMismatchMessage(language: Language): string {
  return language === "en"
    ? "The server returned a different language than requested. Restart or update the service, then try again."
    : "后端返回的结果语言与当前请求不一致，请重启或更新服务后重试。";
}

export function normalizeField(name: string) {
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

export function normalizeResearchQuestion(value?: string | null) {
  if (typeof value !== "string") return "";
  return value.normalize("NFKC").replace(/\s+/g, " ").trim().slice(0, 1000);
}

/**
 * Keep the old key for fields without an original question. A question-aware
 * key prevents two goals that resolve to the same canonical field from
 * sharing a completed result or an in-flight request.
 */
export const requestKey = (
  name: string,
  mode: Mode,
  researchQuestion?: string | null,
  language: Language = "zh-CN",
) => {
  const requestLanguage = normalizeLanguage(language);
  // Keep the historical Chinese key byte-for-byte compatible. English gets a
  // dedicated namespace so the same canonical field/question can never
  // overwrite a Chinese result in memory or local session storage.
  const base = `${mode}:${normalizeField(name)}${
    requestLanguage === "en" ? ":lang:en" : ""
  }`;
  const question = normalizeResearchQuestion(researchQuestion);
  return question ? `${base}:q:${encodeURIComponent(question)}` : base;
};

export type TrailContexts = Record<string, string>;

/**
 * Update a breadcrumb path while keeping the original-question context tied
 * to its path position. Child fields intentionally receive no inherited
 * question; returning to a root uses the context saved at that position.
 */
export function nextTrailState(
  trail: readonly string[],
  contexts: TrailContexts,
  resultName: string,
  researchQuestion?: string | null,
  resetPath = false,
): { trail: string[]; contexts: TrailContexts } {
  const normalizedQuestion = normalizeResearchQuestion(researchQuestion);
  const existingIndex = resetPath
    ? -1
    : [...trail]
        .map((name) => normalizeField(name))
        .lastIndexOf(normalizeField(resultName));
  const nextTrail =
    resetPath || existingIndex < 0
      ? resetPath
        ? [resultName]
        : [...trail, resultName]
      : trail.slice(0, existingIndex + 1);
  const resultIndex = resetPath
    ? 0
    : existingIndex < 0
      ? nextTrail.length - 1
      : existingIndex;
  const nextContexts: TrailContexts = {};
  for (const [index, question] of Object.entries(contexts)) {
    if (Number(index) < nextTrail.length) nextContexts[index] = question;
  }
  if (normalizedQuestion)
    nextContexts[String(resultIndex)] = normalizedQuestion;
  else delete nextContexts[String(resultIndex)];
  return { trail: nextTrail, contexts: nextContexts };
}

type Listener = (event: ExploreEvent) => void;
type FetchField = (
  name: string,
  mode: Mode,
  refresh: boolean,
  listener: Listener,
  signal: AbortSignal,
  researchQuestion?: string,
  language?: Language,
) => Promise<FieldNode>;
type Job = {
  controller: AbortController;
  promise: Promise<FieldNode>;
  listeners: Set<Listener>;
  latest?: ExploreEvent;
};

/** Own network jobs independently of which field is currently displayed. */
export class ExplorationRequests {
  private cache = new Map<string, FieldNode>();
  private jobs = new Map<string, Job>();
  private selection = 0;
  private fetchField: FetchField;

  constructor(fetchField: FetchField) {
    this.fetchField = fetchField;
  }
  select() {
    return ++this.selection;
  }
  isCurrent(ticket: number) {
    return this.selection === ticket;
  }
  hasPending(key: string) {
    return this.jobs.has(key);
  }
  cancel(key: string) {
    const job = this.jobs.get(key);
    if (!job) return;
    // Remove the aborted job before signalling it so an immediate retry can
    // create a fresh request. The old promise's finally block is identity
    // guarded and therefore cannot delete the replacement job.
    this.jobs.delete(key);
    job.controller.abort();
  }
  dispose() {
    const jobs = [...this.jobs.values()];
    this.jobs.clear();
    for (const job of jobs) job.controller.abort();
    this.cache.clear();
  }

  async explore(
    name: string,
    mode: Mode,
    refresh: boolean,
    listener: Listener,
    researchQuestion?: string,
    language: Language = "zh-CN",
  ): Promise<FieldNode> {
    const normalizedQuestion = normalizeResearchQuestion(researchQuestion);
    const requestLanguage = normalizeLanguage(language);
    const key = requestKey(name, mode, normalizedQuestion, requestLanguage);
    const cached = this.cache.get(key);
    if (cached && !refresh) return { ...cached, cache_hit: true };
    const existing = this.jobs.get(key);
    if (existing) {
      existing.listeners.add(listener);
      if (existing.latest) listener(existing.latest);
      try {
        return await existing.promise;
      } finally {
        existing.listeners.delete(listener);
      }
    }
    const job: Job = {
      controller: new AbortController(),
      listeners: new Set([listener]),
      promise: undefined!,
    };
    this.jobs.set(key, job);
    job.promise = Promise.resolve()
      .then(() =>
        this.fetchField(
          name,
          mode,
          refresh,
          (event) => {
            const contextualEvent =
              event.type === "partial" || event.type === "complete"
                ? (() => {
                    if (
                      event.field.language !== undefined &&
                      event.field.language !== requestLanguage
                    )
                      throw new Error(languageMismatchMessage(requestLanguage));
                    return {
                      ...event,
                      field: {
                        ...event.field,
                        // Mocks and old adapters may omit the marker. The
                        // production API validates it before this layer, so
                        // an omitted marker can retain the requested language;
                        // an explicit mismatch is always rejected.
                        language: event.field.language ?? requestLanguage,
                        ...(normalizedQuestion &&
                        !normalizeResearchQuestion(
                          event.field.research_question,
                        )
                          ? { research_question: normalizedQuestion }
                          : {}),
                      },
                    };
                  })()
                : event;
            job.latest = contextualEvent;
            for (const fn of job.listeners) fn(contextualEvent);
          },
          job.controller.signal,
          normalizedQuestion || undefined,
          requestLanguage,
        ),
      )
      .then((result) => {
        if (job.controller.signal.aborted)
          throw new DOMException("Cancelled", "AbortError");
        // A papers/map terminal response is useful to the current caller, but
        // it is not a reusable field snapshot. Only the complete phase may
        // become a cache hit on a later exploration.
        const contextualResult =
          normalizedQuestion &&
          !normalizeResearchQuestion(result.research_question)
            ? { ...result, research_question: normalizedQuestion }
            : result;
        if (
          contextualResult.language !== undefined &&
          contextualResult.language !== requestLanguage
        )
          throw new Error(languageMismatchMessage(requestLanguage));
        const languageResult = {
          ...contextualResult,
          language: contextualResult.language ?? requestLanguage,
        };
        if (languageResult.phase === "complete") {
          this.cache.set(key, languageResult);
          this.cache.set(
            requestKey(
              languageResult.name,
              mode,
              normalizedQuestion,
              requestLanguage,
            ),
            languageResult,
          );
        }
        return languageResult;
      })
      .finally(() => {
        if (this.jobs.get(key) === job) this.jobs.delete(key);
      });
    return job.promise;
  }
}
