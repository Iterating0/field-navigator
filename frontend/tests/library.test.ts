import { test } from "node:test";
import assert from "node:assert/strict";
import type { CorePaper, Paper } from "../src/types/index.ts";
import {
  LIBRARY_STORAGE_KEY,
  MAX_LIBRARY_ITEMS,
  MAX_NOTE_LENGTH,
  addToLibrary,
  exportLibraryMarkdown,
  loadLibrary,
  normalizeLibrary,
  saveLibrary,
  updateLibraryItem,
} from "../src/state/library.ts";

class MemoryStorage {
  private readonly values = new Map<string, string>();
  failWrites = false;

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (this.failWrites) throw new Error("quota exceeded");
    this.values.set(key, value);
  }
}

function paper(overrides: Partial<Paper> = {}): Paper {
  return {
    id: "openalex:W1",
    title: "A useful paper",
    year: 2024,
    authors: ["A. Researcher"],
    citation_count: 12,
    doi: "10.1000/example",
    url: "https://example.org/paper",
    journal: "Example Journal",
    source: "openalex",
    ...overrides,
  };
}

function core(fieldReason: string, overrides: Partial<Paper> = {}): CorePaper {
  return {
    paper: paper(overrides),
    score: 0.9,
    reason: fieldReason,
    signals: { relevance: 0.9 },
  };
}

test("the same DOI is deduplicated while source fields and reasons are retained", () => {
  const first = addToLibrary(
    [],
    core("A foundation for the field", { citation_count: null }),
    "量子材料",
  );
  const merged = addToLibrary(
    first,
    core("A route to experimental validation", {
      id: "openalex:W2",
      doi: "https://doi.org/10.1000/EXAMPLE",
      title: "A useful paper (alternate record)",
      citation_count: 999,
    }),
    "凝聚态实验",
  );

  assert.equal(merged.length, 1);
  assert.deepEqual(
    [...merged[0].fields].sort(),
    ["凝聚态实验", "量子材料"].sort(),
  );
  assert.match(merged[0].reason, /量子材料：A foundation/);
  assert.match(merged[0].reason, /凝聚态实验：A route/);
  assert.equal(merged[0].id, "doi:10.1000/example");
  assert.equal(merged[0].paper.citation_count, null);
});

test("official metadata replaces stale indexed fields while user state survives", () => {
  const indexed = addToLibrary(
    [],
    core("The stale indexed contribution", {
      id: "openalex:W-verified",
      title: "Wrong indexed title",
      citation_count: 99999,
      doi: null,
      url: "https://arxiv.org/abs/2401.12345v1",
      source: "openalex",
      source_record_ids: ["W-verified", "https://arxiv.org/abs/2401.12345v1"],
    }),
    "索引记录",
  );
  const savedAt = indexed[0].saved_at;
  const withUserState = updateLibraryItem(indexed, indexed[0].id, {
    status: "read",
    note: "private note",
  });

  const corrected = addToLibrary(
    withUserState,
    core("The official verified contribution", {
      id: "openalex:W-verified",
      title: "Correct official title",
      citation_count: null,
      doi: "10.48550/arXiv.2401.12345",
      url: "https://arxiv.org/abs/2401.12345",
      source: "arxiv",
      abstract: "The official abstract.",
      work_type: "preprint",
      work_version: "submittedVersion",
      source_record_ids: ["W-verified", "https://arxiv.org/abs/2401.12345"],
      abstract_source_record_id: "https://arxiv.org/abs/2401.12345",
    }),
    "核验记录",
  );

  assert.equal(corrected.length, 1);
  const item = corrected[0];
  assert.equal(item.paper.title, "Correct official title");
  assert.equal(item.paper.citation_count, null);
  assert.equal(item.paper.abstract, "The official abstract.");
  assert.equal(item.paper.source, "arxiv");
  assert.equal(
    item.paper.abstract_source_record_id,
    "https://arxiv.org/abs/2401.12345",
  );
  assert.ok(
    item.paper.source_record_ids?.includes(
      "https://arxiv.org/abs/2401.12345v1",
    ),
  );
  assert.equal(item.status, "read");
  assert.equal(item.note, "private note");
  assert.equal(item.saved_at, savedAt);
  assert.deepEqual([...item.fields].sort(), ["索引记录", "核验记录"].sort());
  assert.match(item.reason, /核验记录：The official verified contribution/);
  assert.doesNotMatch(item.reason, /索引记录：The stale indexed contribution/);
});

test("an arXiv DOI overrides a stale published-version label", () => {
  const indexed = addToLibrary(
    [],
    core("The stale DOI contribution", {
      id: "openalex:W-arxiv-doi",
      title: "Wrong indexed title",
      citation_count: 99999,
      doi: "10.48550/arXiv.2401.12345",
      url: "https://arxiv.org/abs/2401.12345v1",
      source: "openalex",
      work_type: "article",
      work_version: "publishedVersion",
      source_record_ids: ["W-arxiv-doi", "https://arxiv.org/abs/2401.12345v1"],
    }),
    "旧索引",
  );
  const corrected = addToLibrary(
    indexed,
    core("The official DOI contribution", {
      id: "openalex:W-arxiv-doi",
      title: "Correct official title",
      citation_count: null,
      doi: "10.48550/arXiv.2401.12345",
      url: "https://arxiv.org/abs/2401.12345",
      source: "arxiv",
      work_type: "preprint",
      work_version: "submittedVersion",
      abstract: "The verified abstract.",
      source_record_ids: ["W-arxiv-doi", "https://arxiv.org/abs/2401.12345"],
      abstract_source_record_id: "https://arxiv.org/abs/2401.12345",
    }),
    "官方核验",
  );

  assert.equal(corrected.length, 1);
  assert.equal(corrected[0].paper.title, "Correct official title");
  assert.equal(corrected[0].paper.citation_count, null);
  assert.equal(corrected[0].paper.work_version, "submittedVersion");
  assert.equal(corrected[0].paper.abstract, "The verified abstract.");
  assert.match(corrected[0].reason, /官方核验：The official DOI contribution/);
  assert.doesNotMatch(
    corrected[0].reason,
    /旧索引：The stale DOI contribution/,
  );
});

test("published and preprint records keep their own citation counts", () => {
  const published = addToLibrary(
    [],
    core("The published contribution", {
      id: "openalex:W-versioned",
      title: "Published canonical title",
      citation_count: null,
      doi: "10.1000/published-version",
      url: "https://example.org/published-version",
      source: "openalex",
      work_type: "article",
      work_version: "published",
      source_record_ids: ["W-versioned", "https://arxiv.org/abs/2401.12345v1"],
    }),
    "发表记录",
  );
  const preprint = addToLibrary(
    [],
    core("The unrelated preprint contribution", {
      id: "openalex:W-versioned",
      title: "Mismatched preprint title",
      citation_count: 99999,
      doi: null,
      url: "https://arxiv.org/abs/2401.12345v1",
      source: "arxiv",
      work_type: "preprint",
      work_version: "submittedVersion",
      source_record_ids: ["W-versioned", "https://arxiv.org/abs/2401.12345v1"],
    }),
    "预印本记录",
  );

  for (const items of [
    [published[0], preprint[0]],
    [preprint[0], published[0]],
  ]) {
    const merged = normalizeLibrary(items);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].paper.title, "Published canonical title");
    assert.equal(merged[0].paper.citation_count, null);
    assert.equal(merged[0].paper.work_version, "published");
    assert.doesNotMatch(merged[0].reason, /Mismatched preprint title/);
    assert.ok(merged[0].fields.includes("发表记录"));
    assert.ok(merged[0].fields.includes("预印本记录"));
  }
});

test("a sparse publisher article is protected from a conflicting verified preprint", () => {
  const published = addToLibrary(
    [],
    core("The publisher record contribution", {
      id: "openalex:W-sparse-published",
      title: "Publisher canonical title",
      citation_count: 321,
      doi: null,
      url: "https://publisher.example/articles/sparse",
      source: "openalex",
      work_type: "article",
      work_version: null,
      // A merged backend work can retain a preprint alias without becoming a
      // preprint record itself.
      source_record_ids: [
        "W-sparse-published",
        "https://arxiv.org/abs/2401.54321v1",
      ],
    }),
    "发表记录",
  );
  const savedAt = published[0].saved_at;
  const withUserState = updateLibraryItem(published, published[0].id, {
    status: "read",
    note: "Keep the publisher record for comparison.",
  });

  const merged = addToLibrary(
    withUserState,
    core("The conflicting verified preprint contribution", {
      id: "openalex:W-sparse-published",
      title: "Conflicting preprint title",
      citation_count: null,
      doi: "10.48550/arXiv.2401.54321",
      url: "https://arxiv.org/abs/2401.54321",
      source: "arxiv",
      abstract: "A verified preprint abstract.",
      work_type: "preprint",
      work_version: "submittedVersion",
      source_record_ids: [
        "W-sparse-published",
        "https://arxiv.org/abs/2401.54321",
      ],
      abstract_source_record_id: "https://arxiv.org/abs/2401.54321",
    }),
    "预印本核验",
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].paper.title, "Publisher canonical title");
  assert.equal(merged[0].paper.citation_count, 321);
  assert.equal(merged[0].paper.url, "https://publisher.example/articles/sparse");
  assert.equal(merged[0].paper.work_version, null);
  assert.equal(merged[0].status, "read");
  assert.equal(merged[0].note, "Keep the publisher record for comparison.");
  assert.equal(merged[0].saved_at, savedAt);
  assert.match(merged[0].reason, /发表记录：The publisher record contribution/);
  assert.doesNotMatch(
    merged[0].reason,
    /预印本核验：The conflicting verified preprint contribution/,
  );
});

test("a full library keeps old papers while a duplicate still merges its source", () => {
  let full = [] as ReturnType<typeof addToLibrary>;
  for (let index = 0; index < MAX_LIBRARY_ITEMS; index++) {
    full = addToLibrary(
      full,
      core(`Original recommendation ${index}`, {
        id: `openalex:W${index}`,
        doi: `10.1000/library-${index}`,
        title: `Library paper ${index}`,
      }),
      `领域 ${index}`,
    );
  }
  assert.equal(full.length, MAX_LIBRARY_ITEMS);
  const originalIds = full.map((item) => item.id);

  const afterNew = addToLibrary(
    full,
    core("This paper would exceed the limit", {
      id: "openalex:W-new",
      doi: "10.1000/library-new",
    }),
    "新领域",
  );
  assert.deepEqual(
    afterNew.map((item) => item.id),
    originalIds,
  );

  const afterDuplicate = addToLibrary(
    full,
    core("A second field uses the same paper", {
      id: "openalex:W-different-record",
      doi: "DOI:10.1000/LIBRARY-42",
    }),
    "交叉领域",
  );
  assert.equal(afterDuplicate.length, MAX_LIBRARY_ITEMS);
  const merged = afterDuplicate.find(
    (item) => item.id === "doi:10.1000/library-42",
  );
  assert.ok(merged);
  assert.ok(merged.fields.includes("交叉领域"));
  assert.match(merged.reason, /交叉领域：A second field/);
  assert.deepEqual(
    afterDuplicate.map((item) => item.id).sort(),
    originalIds.sort(),
  );
});

test("notes and read status survive persistence and notes are bounded", () => {
  const storage = new MemoryStorage();
  const initial = addToLibrary([], core("Read this next"), "AI for Science");
  assert.equal(saveLibrary(initial, storage as unknown as Storage), true);

  const loaded = loadLibrary(storage as unknown as Storage);
  const note = "x".repeat(MAX_NOTE_LENGTH + 100);
  const updated = updateLibraryItem(loaded, loaded[0].id, {
    status: "read",
    note,
  });
  assert.equal(updated[0].status, "read");
  assert.equal(updated[0].note.length, MAX_NOTE_LENGTH);

  assert.equal(saveLibrary(updated, storage as unknown as Storage), true);
  const roundTripped = loadLibrary(storage as unknown as Storage);
  assert.equal(roundTripped[0].status, "read");
  assert.equal(roundTripped[0].note.length, MAX_NOTE_LENGTH);
});

test("reload keeps work provenance and merges a later source-record alias", () => {
  const storage = new MemoryStorage();
  const published = addToLibrary(
    [],
    core("Published record is the primary reading start", {
      id: "openalex:Wpub",
      doi: null,
      work_type: "article",
      work_version: "published",
      source_record_ids: ["Wpub", "Wpre"],
      abstract_source_record_id: "Wpre",
      is_retracted: false,
      is_paratext: false,
    }),
    "界面超导",
  );
  const withNotes = updateLibraryItem(published, published[0].id, {
    status: "read",
    note: "Keep the published record and verify the merged abstract.",
  });
  assert.equal(saveLibrary(withNotes, storage as unknown as Storage), true);

  const loaded = loadLibrary(storage as unknown as Storage);
  const merged = addToLibrary(
    loaded,
    core("The preprint record is an alternate source", {
      id: "openalex:Wpre",
      doi: null,
      work_type: "article",
      work_version: "preprint",
      source_record_ids: ["Wpre"],
      abstract_source_record_id: null,
      is_retracted: false,
      is_paratext: false,
    }),
    "氧化物界面",
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].status, "read");
  assert.equal(
    merged[0].note,
    "Keep the published record and verify the merged abstract.",
  );
  assert.deepEqual(merged[0].paper.source_record_ids, ["Wpub", "Wpre"]);
  assert.equal(merged[0].paper.work_version, "published");
  assert.equal(merged[0].paper.abstract_source_record_id, "Wpre");
  assert.equal(merged[0].paper.is_retracted, false);
  assert.equal(merged[0].paper.is_paratext, false);
  assert.deepEqual(
    [...merged[0].fields].sort(),
    ["界面超导", "氧化物界面"].sort(),
  );
});

test("corrupt storage is harmless and write failures are reported", () => {
  const storage = new MemoryStorage();
  storage.setItem(LIBRARY_STORAGE_KEY, "{not json");
  assert.deepEqual(loadLibrary(storage as unknown as Storage), []);

  storage.failWrites = true;
  assert.equal(
    saveLibrary(
      addToLibrary([], core("Save me"), "测试领域"),
      storage as unknown as Storage,
    ),
    false,
  );
});

test("markdown export keeps safe links and escapes untrusted title and notes", () => {
  const unsafe = addToLibrary(
    [],
    core("Read <script> carefully", {
      id: "unsafe",
      title: "<script>alert(1)</script> [title]",
      url: "javascript:alert(1)",
    }),
    "安全研究",
  );
  const unsafeWithNote = updateLibraryItem(unsafe, unsafe[0].id, {
    note: "<img src=x onerror=alert(1)> [click](javascript:alert(1))",
  });
  const safe = addToLibrary(
    unsafeWithNote,
    core("A public source", {
      id: "safe",
      doi: "10.1000/safe",
      title: "A public paper",
      url: "https://example.org/safe paper",
    }),
    "可复现研究",
  );

  const markdown = exportLibraryMarkdown(safe);
  assert.match(markdown, /### &lt;script&gt;alert/);
  assert.match(markdown, /&lt;img src=x onerror=alert/);
  assert.doesNotMatch(markdown, /<script>|<img/i);
  assert.doesNotMatch(markdown, /\]\(javascript:/i);
  assert.match(markdown, /https:\/\/example\.org\/safe%20paper/);
  assert.doesNotMatch(markdown, /model|api[_ -]?key|secret/i);
});
