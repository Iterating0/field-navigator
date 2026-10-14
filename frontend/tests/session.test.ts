import { test } from "node:test";
import assert from "node:assert/strict";
import type { FieldNode } from "../src/types/index.ts";
import {
  LEGACY_SESSION_STORAGE_KEY,
  SESSION_STORAGE_KEY,
  clearSession,
  loadSession,
  saveSession,
  type Session,
  type SessionStorage,
} from "../src/state/session.ts";
import { requestKey } from "../src/state/exploration.ts";

class MemoryStorage implements SessionStorage {
  values = new Map<string, string>();
  failGet = false;
  failSet = false;
  failRemove = false;

  getItem(key: string) {
    if (this.failGet) throw new Error("storage read failed");
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    if (this.failSet) throw new Error("quota exceeded");
    this.values.set(key, value);
  }

  removeItem(key: string) {
    if (this.failRemove) throw new Error("storage remove failed");
    this.values.delete(key);
  }
}

function field(
  name: string,
  phase: FieldNode["phase"] = "complete",
): FieldNode {
  return {
    id: name.toLowerCase().replace(/\s+/g, "-"),
    name,
    summary: `${name} summary`,
    prerequisites: [],
    subfields: [],
    core_papers: [],
    paper_source: "openalex",
    analysis_source: "llm",
    phase,
    candidate_count: 2,
    analyzed_paper_count: phase === "complete" ? 2 : 0,
    warnings: [],
    created_at: "2026-10-13T00:00:00Z",
    cache_hit: false,
    quality_revision: 10,
  };
}

test("defaults are stable and v1 migration never fabricates a snapshot", () => {
  const storage = new MemoryStorage();
  assert.deepEqual(loadSession(storage), {
    history: [],
    current: "",
    mode: "auto",
    snapshots: {},
    trail: [],
  });

  storage.setItem(
    LEGACY_SESSION_STORAGE_KEY,
    JSON.stringify({
      history: [{ name: "Quantum transport", parent: null }],
      current: "Quantum transport",
      mode: "live",
    }),
  );
  const migrated = loadSession(storage);
  assert.equal(migrated.current, "Quantum transport");
  assert.equal(migrated.mode, "live");
  assert.deepEqual(migrated.snapshots, {});
  assert.deepEqual(migrated.trail, []);
  assert.equal(migrated.history[0]?.mode, "live");
});

test("demo and live snapshots are isolated and arbitrary fields are dropped", () => {
  const storage = new MemoryStorage();
  const live = Object.assign(field("Quantum transport"), {
    extraAPIKey: "must-not-persist",
    private_notes: "must-not-persist",
  }) as FieldNode;
  const demo = field("Quantum transport");
  const session: Session = {
    history: [
      { name: live.name, parent: null, mode: "live" },
      { name: demo.name, parent: null, mode: "demo" },
    ],
    current: live.name,
    mode: "live",
    snapshots: {
      [requestKey(live.name, "live")]: live,
      [requestKey(demo.name, "demo")]: demo,
    },
    trail: ["Quantum transport"],
  };

  assert.equal(saveSession(session, storage), true);
  const raw = storage.values.get(SESSION_STORAGE_KEY) ?? "";
  assert.equal(raw.includes("extraAPIKey"), false);
  assert.equal(raw.includes("private_notes"), false);
  const loaded = loadSession(storage);
  assert.deepEqual(Object.keys(loaded.snapshots).sort(), [
    requestKey(demo.name, "demo"),
    requestKey(live.name, "live"),
  ]);
  assert.equal(
    loaded.snapshots[requestKey(live.name, "live")]?.name,
    "Quantum transport",
  );
});

test("only complete snapshots are persisted and session bounds are enforced", () => {
  const storage = new MemoryStorage();
  const snapshots: Record<string, FieldNode> = {
    [requestKey("Papers only", "auto")]: field("Papers only", "papers"),
    [requestKey("Map only", "auto")]: field("Map only", "map"),
  };
  for (let index = 0; index < 10; index++) {
    const complete = field(`Complete ${index}`);
    snapshots[requestKey(complete.name, "auto")] = complete;
  }
  const history = Array.from({ length: 55 }, (_, index) => ({
    name: `Topic ${index}`,
    parent: null,
    mode: "auto" as const,
  }));
  assert.equal(
    saveSession(
      {
        history,
        current: "Topic 54",
        mode: "auto",
        snapshots,
        trail: [],
      },
      storage,
    ),
    true,
  );
  const loaded = loadSession(storage);
  assert.equal(Object.keys(loaded.snapshots).length, 8);
  assert.equal(loaded.snapshots[requestKey("Papers only", "auto")], undefined);
  assert.equal(loaded.snapshots[requestKey("Map only", "auto")], undefined);
  assert.equal(loaded.history.length, 50);
  assert.equal(loaded.history[0]?.name, "Topic 5");
  assert.equal(loaded.history.at(-1)?.name, "Topic 54");
});

test("pre-audit live snapshots are ignored while demo snapshots remain usable", () => {
  const storage = new MemoryStorage();
  const stale = field("Stale live");
  stale.quality_revision = 9;
  const currentDemo = field("Stale demo");
  delete currentDemo.quality_revision;
  storage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({
      mode: "auto",
      current: stale.name,
      history: [],
      trail: [],
      snapshots: {
        [requestKey(stale.name, "live")]: stale,
        [requestKey(currentDemo.name, "demo")]: currentDemo,
      },
    }),
  );
  const loaded = loadSession(storage);
  assert.equal(loaded.snapshots[requestKey(stale.name, "live")], undefined);
  assert.equal(
    loaded.snapshots[requestKey(currentDemo.name, "demo")]?.name,
    currentDemo.name,
  );
});

test("relation claim maturity survives session storage and legacy data defaults safely", () => {
  const storage = new MemoryStorage();
  const legacy = field("Legacy relation maturity");
  legacy.subfields = [
    {
      name: "Candidate mechanism",
      reason: "A possible explanation.",
      confidence: 0.5,
      evidence_paper_ids: [],
    },
  ];
  storage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({
      mode: "auto",
      current: legacy.name,
      history: [],
      trail: [legacy.name],
      snapshots: { [requestKey(legacy.name, "auto")]: legacy },
    }),
  );
  const loadedLegacy = loadSession(storage);
  assert.equal(
    loadedLegacy.snapshots[requestKey(legacy.name, "auto")]?.subfields[0]
      ?.claim_level,
    "research_direction",
  );

  legacy.subfields[0].claim_level = "theory_or_proposed";
  assert.equal(
    saveSession(
      {
        history: [],
        current: legacy.name,
        mode: "auto",
        snapshots: { [requestKey(legacy.name, "auto")]: legacy },
        trail: [legacy.name],
      },
      storage,
    ),
    true,
  );
  const loadedCurrent = loadSession(storage);
  assert.equal(
    loadedCurrent.snapshots[requestKey(legacy.name, "auto")]?.subfields[0]
      ?.claim_level,
    "theory_or_proposed",
  );
});

test("question-aware snapshots and history entries survive persistence", () => {
  const storage = new MemoryStorage();
  const first = {
    ...field("Same canonical field"),
    research_question: "How does temperature affect the interface?",
  };
  const second = {
    ...field("Same canonical field"),
    research_question: "Which device geometry changes the interface?",
  };
  const firstKey = requestKey(first.name, "auto", first.research_question);
  const secondKey = requestKey(second.name, "auto", second.research_question);
  assert.notEqual(firstKey, secondKey);
  assert.equal(
    saveSession(
      {
        history: [
          {
            name: first.name,
            parent: null,
            mode: "auto",
            research_question: first.research_question,
          },
          {
            name: second.name,
            parent: null,
            mode: "auto",
            research_question: second.research_question,
          },
        ],
        current: second.name,
        current_research_question: second.research_question,
        mode: "auto",
        snapshots: { [firstKey]: first, [secondKey]: second },
        trail: [first.name, second.name],
        trail_contexts: { "0": first.research_question },
      },
      storage,
    ),
    true,
  );
  const loaded = loadSession(storage);
  assert.equal(loaded.history.length, 2);
  assert.equal(loaded.current_research_question, second.research_question);
  assert.equal(loaded.trail_contexts?.["0"], first.research_question);
  assert.equal(
    loaded.snapshots[firstKey]?.research_question,
    first.research_question,
  );
  assert.equal(
    loaded.snapshots[secondKey]?.research_question,
    second.research_question,
  );
});

test("corrupt reads and quota failures are safe and visible as booleans", () => {
  const corrupted = new MemoryStorage();
  corrupted.values.set(SESSION_STORAGE_KEY, "not-json");
  assert.deepEqual(loadSession(corrupted).snapshots, {});

  const readFailure = new MemoryStorage();
  readFailure.failGet = true;
  assert.deepEqual(loadSession(readFailure).history, []);

  const quota = new MemoryStorage();
  quota.failSet = true;
  assert.equal(saveSession(loadSession(), quota), false);

  const clearFailure = new MemoryStorage();
  clearFailure.failRemove = true;
  assert.equal(clearSession(clearFailure), false);
});

test("clearSession removes both current and legacy records", () => {
  const storage = new MemoryStorage();
  storage.values.set(SESSION_STORAGE_KEY, "{}");
  storage.values.set(LEGACY_SESSION_STORAGE_KEY, "{}");
  assert.equal(clearSession(storage), true);
  assert.equal(storage.values.has(SESSION_STORAGE_KEY), false);
  assert.equal(storage.values.has(LEGACY_SESSION_STORAGE_KEY), false);
});
