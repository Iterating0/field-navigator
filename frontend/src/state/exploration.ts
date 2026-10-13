import type { ExploreEvent, FieldNode, Mode } from "../types";

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

export const requestKey = (name: string, mode: Mode) =>
  `${mode}:${normalizeField(name)}`;
type Listener = (event: ExploreEvent) => void;
type FetchField = (
  name: string,
  mode: Mode,
  refresh: boolean,
  listener: Listener,
  signal: AbortSignal,
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
    this.jobs.get(key)?.controller.abort();
  }
  dispose() {
    for (const job of this.jobs.values()) job.controller.abort();
  }

  async explore(
    name: string,
    mode: Mode,
    refresh: boolean,
    listener: Listener,
  ): Promise<FieldNode> {
    const key = requestKey(name, mode);
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
            job.latest = event;
            for (const fn of job.listeners) fn(event);
          },
          job.controller.signal,
        ),
      )
      .then((result) => {
        if (job.controller.signal.aborted)
          throw new DOMException("Cancelled", "AbortError");
        this.cache.set(key, result);
        this.cache.set(requestKey(result.name, mode), result);
        return result;
      })
      .finally(() => {
        if (this.jobs.get(key) === job) this.jobs.delete(key);
      });
    return job.promise;
  }
}
