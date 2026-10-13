import { test } from "node:test";
import assert from "node:assert/strict";
import { ExplorationRequests, requestKey } from "../src/state/exploration.ts";
import type { FieldNode, ExploreEvent } from "../src/types/index.ts";

function field(name: string): FieldNode {
  return {
    id: name,
    name,
    summary: "Ready",
    prerequisites: [],
    subfields: [],
    core_papers: [],
    paper_source: "openalex",
    analysis_source: "llm",
    phase: "complete",
    candidate_count: 1,
    warnings: [],
    created_at: "",
    cache_hit: false,
  };
}
const tick = () => new Promise<void>((resolve) => queueMicrotask(resolve));

test("slow background completion cannot replace the selected cached field", async () => {
  let release!: (field: FieldNode) => void;
  const store = new ExplorationRequests(async (name) =>
    name === "Slow"
      ? new Promise((resolve) => {
          release = resolve;
        })
      : field(name),
  );
  await store.explore("Cached", "auto", false, () => {});
  const old = store.select();
  const pending = store.explore("Slow", "auto", false, () => {});
  await tick();
  const current = store.select();
  assert.equal(
    (await store.explore("Cached", "auto", false, () => {})).cache_hit,
    true,
  );
  release(field("Slow"));
  await pending;
  assert.equal(store.isCurrent(old), false);
  assert.equal(store.isCurrent(current), true);
  assert.equal(
    (await store.explore("Slow", "auto", false, () => {})).cache_hit,
    true,
  );
});

test("aliases share pending work and replay the latest partial event", async () => {
  let calls = 0;
  let release!: (field: FieldNode) => void;
  const store = new ExplorationRequests(async (_, __, ___, emit) => {
    calls++;
    emit({
      type: "partial",
      stage: "papers",
      field: { ...field("NHSE"), phase: "papers" },
    });
    return new Promise((resolve) => {
      release = resolve;
    });
  });
  const a = store.explore("NHSE", "auto", false, () => {});
  await tick();
  const seen: ExploreEvent[] = [];
  const b = store.explore("非厄米趋肤效应", "auto", false, (event) =>
    seen.push(event),
  );
  assert.equal(calls, 1);
  assert.equal(seen[0].type, "partial");
  release(field("Non-Hermitian Skin Effect"));
  await Promise.all([a, b]);
});

test("cancellation prevents caching and allows retry, modes are isolated", async () => {
  let calls = 0;
  const store = new ExplorationRequests(async (name, _, __, ___, signal) => {
    calls++;
    if (calls === 1)
      return new Promise((_, reject) =>
        signal.addEventListener("abort", () =>
          reject(new DOMException("Cancelled", "AbortError")),
        ),
      );
    return field(name);
  });
  const pending = store.explore("Test", "auto", false, () => {});
  await tick();
  store.cancel(requestKey("Test", "auto"));
  await assert.rejects(pending, { name: "AbortError" });
  await store.explore("Test", "auto", false, () => {});
  await store.explore("Test", "live", false, () => {});
  assert.equal(calls, 3);
});

test("returning to a cached field does not hide its active refresh", async () => {
  let release!: (field: FieldNode) => void;
  const store = new ExplorationRequests(async (name, _, refresh) =>
    refresh
      ? new Promise((resolve) => {
          release = resolve;
        })
      : field(name),
  );
  await store.explore("Test", "auto", false, () => {});
  const refresh = store.explore("Test", "auto", true, () => {});
  await tick();
  assert.equal(
    (await store.explore("Test", "auto", false, () => {})).cache_hit,
    true,
  );
  assert.equal(store.hasPending(requestKey("Test", "auto")), true);
  release(field("Test"));
  await refresh;
  assert.equal(store.hasPending(requestKey("Test", "auto")), false);
});
