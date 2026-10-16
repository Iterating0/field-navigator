import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ExplorationRequests,
  nextTrailState,
  requestKey,
} from "../src/state/exploration.ts";
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

test("papers and map terminal results are returned without becoming cache hits", async () => {
  let calls = 0;
  const store = new ExplorationRequests(async (name) => {
    calls++;
    const phase: FieldNode["phase"] =
      calls === 1 ? "papers" : calls === 2 ? "map" : "complete";
    return { ...field(name), phase };
  });

  const papers = await store.explore("Partial", "auto", false, () => {});
  assert.equal(papers.phase, "papers");
  assert.equal(papers.cache_hit, false);
  const map = await store.explore("Partial", "auto", false, () => {});
  assert.equal(map.phase, "map");
  assert.equal(map.cache_hit, false);
  const complete = await store.explore("Partial", "auto", false, () => {});
  assert.equal(complete.phase, "complete");
  assert.equal(complete.cache_hit, false);

  const cached = await store.explore("Partial", "auto", false, () => {});
  assert.equal(cached.phase, "complete");
  assert.equal(cached.cache_hit, true);
  assert.equal(calls, 3);
});

test("cancel and dispose release a key before an immediate retry", async () => {
  let calls = 0;
  const store = new ExplorationRequests(async (name, _, __, ___, signal) => {
    calls++;
    if (calls === 1 || (name === "Dispose" && calls === 3)) {
      return new Promise<FieldNode>((_, reject) => {
        signal.addEventListener("abort", () => {
          // Keep the old promise pending briefly to exercise the retry race.
          setTimeout(
            () => reject(new DOMException("Cancelled", "AbortError")),
            20,
          );
        });
      });
    }
    return field(name);
  });

  const first = store.explore("Retry", "auto", false, () => {});
  await tick();
  store.cancel(requestKey("Retry", "auto"));
  const second = store.explore("Retry", "auto", false, () => {});
  assert.equal((await second).name, "Retry");
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(calls, 2);

  const waiting = store.explore("Dispose", "auto", true, () => {});
  await tick();
  store.dispose();
  const retry = store.explore("Dispose", "auto", true, () => {});
  await assert.rejects(waiting, { name: "AbortError" });
  assert.equal((await retry).name, "Dispose");
  assert.equal(calls, 4);
});

test("dispose also clears completed memory cache", async () => {
  let calls = 0;
  const store = new ExplorationRequests(async (name) => {
    calls++;
    return field(name);
  });
  await store.explore("Cleared", "auto", false, () => {});
  assert.equal(
    (await store.explore("Cleared", "auto", false, () => {})).cache_hit,
    true,
  );
  store.dispose();
  assert.equal(
    (await store.explore("Cleared", "auto", false, () => {})).cache_hit,
    false,
  );
  assert.equal(calls, 2);
});

test("distinct original questions do not share a canonical field cache", async () => {
  let calls = 0;
  const store = new ExplorationRequests(
    async (name, _, __, ___, ____, researchQuestion) => {
      calls++;
      return {
        ...field(name),
        research_question: researchQuestion ?? null,
      };
    },
  );
  const questionA = "Which interface mechanism raises Tc?";
  const questionB = "How does disorder change the interface phase diagram?";
  const first = await store.explore(
    "KTaO3 interface superconductivity",
    "auto",
    false,
    () => {},
    questionA,
  );
  const second = await store.explore(
    "KTaO3 interface superconductivity",
    "auto",
    false,
    () => {},
    questionB,
  );
  assert.equal(calls, 2);
  assert.equal(first.research_question, questionA);
  assert.equal(second.research_question, questionB);
  assert.notEqual(
    requestKey("KTaO3 interface superconductivity", "auto", questionA),
    requestKey("KTaO3 interface superconductivity", "auto", questionB),
  );
  assert.equal(
    (
      await store.explore(
        "KTaO3 interface superconductivity",
        "auto",
        false,
        () => {},
        questionA,
      )
    ).cache_hit,
    true,
  );
  assert.equal(calls, 2);
});

test("Chinese and English canonical fields never share cache or in-flight work", async () => {
  let calls = 0;
  const store = new ExplorationRequests(
    async (name, _, __, ___, ____, researchQuestion, language) => {
      calls++;
      return {
        ...field(name),
        language,
        research_question: researchQuestion ?? null,
      };
    },
  );
  const question = "Which mechanism controls the transition?";
  const chinese = await store.explore(
    "Same canonical field",
    "auto",
    false,
    () => {},
    question,
    "zh-CN",
  );
  const english = await store.explore(
    "Same canonical field",
    "auto",
    false,
    () => {},
    question,
    "en",
  );

  assert.equal(calls, 2);
  assert.equal(chinese.language, "zh-CN");
  assert.equal(english.language, "en");
  assert.notEqual(
    requestKey("Same canonical field", "auto", question, "zh-CN"),
    requestKey("Same canonical field", "auto", question, "en"),
  );
  assert.equal(
    (
      await store.explore(
        "Same canonical field",
        "auto",
        false,
        () => {},
        question,
        "en",
      )
    ).cache_hit,
    true,
  );
  assert.equal(calls, 2);
});

test("an explicit language mismatch cannot populate the requested cache", async () => {
  let calls = 0;
  const store = new ExplorationRequests(async (name) => {
    calls++;
    return {
      ...field(name),
      language: calls === 1 ? "zh-CN" : "en",
    };
  });
  const key = requestKey("Mismatched field", "auto", undefined, "en");
  await assert.rejects(
    store.explore("Mismatched field", "auto", false, () => {}, undefined, "en"),
    /different language/i,
  );
  assert.equal(store.hasPending(key), false);

  const recovered = await store.explore(
    "Mismatched field",
    "auto",
    false,
    () => {},
    undefined,
    "en",
  );
  assert.equal(recovered.language, "en");
  assert.equal(recovered.cache_hit, false);
  assert.equal(calls, 2);
  assert.equal(
    (
      await store.explore(
        "Mismatched field",
        "auto",
        false,
        () => {},
        undefined,
        "en",
      )
    ).cache_hit,
    true,
  );
});

test("a stale goal completion is not eligible to update the current graph", async () => {
  const questionA = "Which interface mechanism raises Tc?";
  const questionB = "How does disorder change the interface phase diagram?";
  let releaseA!: (value: FieldNode) => void;
  let releaseB!: (value: FieldNode) => void;
  const store = new ExplorationRequests(
    async (name, _, __, ___, ____, researchQuestion) =>
      new Promise<FieldNode>((resolve) => {
        if (researchQuestion === questionA) releaseA = resolve;
        else releaseB = resolve;
      }),
  );

  const ticketA = store.select();
  const first = store.explore(
    "KTaO3 interface superconductivity",
    "auto",
    false,
    () => {},
    questionA,
  );
  await tick();
  const ticketB = store.select();
  const second = store.explore(
    "KTaO3 interface superconductivity",
    "auto",
    false,
    () => {},
    questionB,
  );
  await tick();

  releaseA({
    ...field("KTaO3 interface superconductivity"),
    research_question: questionA,
  });
  releaseB({
    ...field("KTaO3 interface superconductivity"),
    research_question: questionB,
  });
  const [resultA, resultB] = await Promise.all([first, second]);
  const graphUpdates: string[] = [];
  if (store.isCurrent(ticketA))
    graphUpdates.push(resultA.research_question ?? "");
  if (store.isCurrent(ticketB))
    graphUpdates.push(resultB.research_question ?? "");

  assert.deepEqual(graphUpdates, [questionB]);
});

test("breadcrumb return restores the root question after an unscoped child", () => {
  const root = "KTaO3 interface superconductivity";
  const child = "Interface pairing mechanisms";
  const questionA = "Which mechanism changes Tc at the interface?";
  const questionB = "How does disorder change the interface phase diagram?";

  let path = nextTrailState([], {}, root, questionA, true);
  path = nextTrailState(path.trail, path.contexts, child, null);
  assert.deepEqual(path.trail, [root, child]);
  assert.equal(path.contexts["0"], questionA);
  assert.equal(path.contexts["1"], undefined);

  path = nextTrailState(path.trail, path.contexts, root, path.contexts["0"]);
  assert.deepEqual(path.trail, [root]);
  assert.equal(path.contexts["0"], questionA);

  const otherGoal = nextTrailState([], {}, root, questionB, true);
  assert.equal(otherGoal.contexts["0"], questionB);
  assert.equal(path.contexts["0"], questionA);
});
