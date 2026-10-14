import { test } from "node:test";
import assert from "node:assert/strict";
import type { FieldNode, Paper } from "../src/types/index.ts";
import {
  buildResearchBrief,
  safeHttpUrl,
  serializeMap,
} from "../src/state/export.ts";

function paper(id: string, title: string, url: string | null): Paper {
  return {
    id,
    title,
    year: 2020,
    authors: ["External Author"],
    citation_count: 12,
    doi: null,
    url,
    journal: "Example Journal",
    source: "openalex",
  };
}

function field(name = "Quantum transport"): FieldNode {
  const first = paper("p1", "First paper", "https://example.org/p1");
  const unsafe = Object.assign(
    paper("p2", "Unsafe [paper]", "javascript:alert(1)"),
    {
      abstract: "metadata only",
      full_text: "must not be exported",
      extraAPIKey: "must not be exported",
    },
  ) as Paper;
  const third = paper("p3", "Third paper", null);
  const fourth = paper("p4", "Fourth paper", "https://example.org/p4");
  return {
    id: name.toLowerCase().replace(/\s+/g, "-"),
    name,
    summary: "A <script>summary</script> with a https://untrusted.example URL.",
    prerequisites: [
      {
        name: "Linear algebra",
        reason: "Provides the basis [with markup].",
        confidence: 0.8,
        evidence_paper_ids: ["p1"],
      },
    ],
    subfields: [
      {
        name: "Topological transport",
        reason: "A related branch.",
        confidence: 0.6,
        evidence_paper_ids: ["p2"],
      },
    ],
    core_papers: [
      { paper: first, score: 0.99, reason: "Top-ranked", signals: {} },
      { paper: unsafe, score: 0.8, reason: "Second", signals: {} },
      { paper: third, score: 0.7, reason: "Third", signals: {} },
      { paper: fourth, score: 0.6, reason: "Fourth", signals: {} },
    ],
    paper_source: "openalex",
    analysis_source: "llm",
    phase: "complete",
    candidate_count: 12,
    analyzed_paper_count: 8,
    warnings: ["Candidate ranking needs review."],
    created_at: "2026-10-13T00:00:00Z",
    cache_hit: false,
    evidence_papers: [first, unsafe],
  };
}

test("safeHttpUrl only accepts HTTP(S) and the brief preserves provenance", () => {
  assert.equal(safeHttpUrl("javascript:alert(1)"), null);
  assert.equal(safeHttpUrl("data:text/html,alert(1)"), null);
  assert.equal(safeHttpUrl("https://example.org/a"), "https://example.org/a");

  const brief = buildResearchBrief(field(), [
    { ...field("Loaded context"), phase: "map" },
  ]);
  assert.match(brief, /## 领域概要/);
  assert.match(brief, /## 前置领域/);
  assert.match(brief, /## 研究分支/);
  assert.match(brief, /## 支持论文引用/);
  assert.match(brief, /## 阅读起点（当前排序前 3）/);
  assert.match(brief, /## 其他核心论文/);
  assert.match(brief, /OpenAlex/);
  assert.match(brief, /候选范围：12 篇候选论文/);
  assert.match(brief, /heuristic/);
  assert.match(brief, /不是系统综述/);
  assert.match(brief, /置信度未校准/);
  assert.match(brief, /全文\/原文/);
  assert.match(brief, /已加载领域/);
  assert.match(brief, /\\<script\\>/);
  assert.doesNotMatch(brief, /<script>/);
  assert.doesNotMatch(brief, /javascript:\s*alert/);
  assert.doesNotMatch(brief, /extraAPIKey|full_text|private_notes/);
});

test("serializeMap emits versioned whitelist JSON and marks incomplete exports", () => {
  const complete = field();
  const incomplete = { ...field("Partial"), phase: "papers" as const };
  const parsed = JSON.parse(
    serializeMap([complete, incomplete], complete.id),
  ) as Record<string, any>;

  assert.equal(parsed.version, 1);
  assert.equal(parsed.format, "field-navigator-map");
  assert.equal(parsed.current_field_id, complete.id);
  assert.equal(parsed.complete, false);
  assert.deepEqual(
    parsed.fields.map((item: Record<string, unknown>) => item.name),
    ["Quantum transport", "Partial"],
  );
  assert.equal(parsed.fields[0].phase, "complete");
  assert.equal(parsed.fields[1].phase, "papers");
  assert.equal(parsed.fields[0].extraAPIKey, undefined);
  assert.equal(parsed.fields[0].full_text, undefined);
  assert.equal(parsed.fields[0].cache_hit, undefined);
  assert.match(parsed.source.limitations.join(" "), /不会在导出中补写/);
  assert.doesNotMatch(
    JSON.stringify(parsed),
    /extraAPIKey|full_text|private_notes/,
  );
});

test("incomplete brief does not invent branches or paper citations", () => {
  const partial = {
    ...field("Partial field"),
    phase: "map" as const,
    subfields: [],
    core_papers: [],
    evidence_papers: [],
  };
  const brief = buildResearchBrief(partial);
  assert.match(brief, /结果只到 map 阶段/);
  assert.match(brief, /不补写未生成的分支或论文判断/);
  assert.match(brief, /未返回可追溯支持论文元数据/);
  assert.match(brief, /未返回核心论文/);
});

test("brief and map preserve bounded evidence quality metadata", () => {
  const current = field("Evidence quality");
  current.quality_revision = 1;
  current.research_question = "Which interface mechanism changes Tc?";
  current.core_papers[0].paper.abstract_source_record_id = "W-merged-preprint";
  current.prerequisites[0] = {
    ...current.prerequisites[0],
    claim_level: "theory_or_proposed",
    evidence_status: "supported",
    evidence_quotes: [
      { paper_id: "p1", source: "abstract", quote: "Short abstract evidence." },
    ],
    evidence_warnings: ["Full text was not checked."],
  };
  current.subfields[0] = {
    ...current.subfields[0],
    claim_level: "title_only",
  };
  current.core_papers[0] = {
    ...current.core_papers[0],
    evidence_basis: "abstract",
    evidence_quote: "A short core paper excerpt.",
    role: "primary",
  };
  const brief = buildResearchBrief(current);
  assert.match(brief, /摘要支持/);
  assert.match(brief, /理论 \/ 候选解释/);
  assert.match(brief, /仅题名线索/);
  assert.match(brief, /Short abstract evidence/);
  assert.match(brief, /原始研究/);
  assert.match(brief, /A short core paper excerpt/);
  assert.match(brief, /原始研究问题/);
  const parsed = JSON.parse(serializeMap([current])) as Record<string, any>;
  assert.equal(parsed.fields[0].quality_revision, 1);
  assert.equal(
    parsed.fields[0].research_question,
    "Which interface mechanism changes Tc?",
  );
  assert.equal(parsed.fields[0].prerequisites[0].evidence_status, "supported");
  assert.equal(
    parsed.fields[0].prerequisites[0].claim_level,
    "theory_or_proposed",
  );
  assert.equal(parsed.fields[0].subfields[0].claim_level, "title_only");
  assert.equal(parsed.fields[0].core_papers[0].role, "primary");
  assert.equal(
    parsed.fields[0].core_papers[0].paper.abstract_source_record_id,
    "W-merged-preprint",
  );
  assert.equal(parsed.fields[0].core_papers[0].full_text, undefined);
});
