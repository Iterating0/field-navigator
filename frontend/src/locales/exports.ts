import { normalizeLanguage, type Language } from "../types/index.ts";

/** Dependency-free labels for exported documents. */
export interface ExportLabels {
  product: string;
  readingList: string;
  exportedAt: string;
  toRead: string;
  read: string;
  authors: string;
  year: string;
  journal: string;
  doi: string;
  fields: string;
  reason: string;
  note: string;
  savedAt: string;
  empty: string;
  source: string;
  demoData: string;
  llmAnalysis: string;
  mockAnalysis: string;
  pendingAnalysis: string;
  candidatePapers: string;
  analyzedPapers: string;
  unknown: string;
  supported: string;
  weak: string;
  toVerify: string;
  researchDirection: string;
  theoryCandidate: string;
  titleOnly: string;
  abstractEvidence: string;
  titleClue: string;
  primary: string;
  review: string;
  background: string;
  nonResearch: string;
  roleToVerify: string;
  metadataIncomplete: string;
  abstractMetadata: string;
  domainSummary: string;
  noSummary: string;
  prerequisites: string;
  researchBranches: string;
  supportingCitations: string;
  citationDisclaimer: string;
  readingStart: string;
  otherCorePapers: string;
  currentLimitations: string;
  loadedFields: string;
  noTraceablePapers: string;
  incompleteNotice: string;
  invalidResult: string;
  heuristicLimit: string;
  confidenceLimit: string;
  metadataLimit: string;
  evidenceLimit: string;
  maturityLimit: string;
  candidateRange: (candidate: number, analyzed: number | null) => string;
  candidateScore: (value: string) => string;
  confidence: (value: string) => string;
  evidence: (value: string) => string;
  maturity: (value: string) => string;
  evidenceMetadata: (value: string) => string;
  excerpt: (source: string, value: string) => string;
  phase: (value: string) => string;
  sourceSummary: (paper: string, analysis: string) => string;
}

const ZH: ExportLabels = {
  product: "Field Navigator",
  readingList: "阅读清单",
  exportedAt: "导出时间",
  toRead: "待读",
  read: "已读",
  authors: "作者",
  year: "年份",
  journal: "期刊",
  doi: "DOI",
  fields: "所属领域",
  reason: "建议理由",
  note: "个人笔记",
  savedAt: "保存时间",
  empty: "清单为空。",
  source: "来源",
  demoData: "demo 数据",
  llmAnalysis: "LLM 分析",
  mockAnalysis: "mock 分析",
  pendingAnalysis: "待分析",
  candidatePapers: "篇候选论文",
  analyzedPapers: "分析了",
  unknown: "未知",
  supported: "摘要支持 · 自动核对",
  weak: "线索有限",
  toVerify: "待核对",
  researchDirection: "文献覆盖方向",
  theoryCandidate: "理论 / 候选解释",
  titleOnly: "仅题名线索",
  abstractEvidence: "摘要证据",
  titleClue: "标题线索",
  primary: "原始研究",
  review: "综述导读",
  background: "背景材料",
  nonResearch: "非研究条目",
  roleToVerify: "角色待核对",
  metadataIncomplete: "元数据不完整",
  abstractMetadata: "摘要仅作为元数据字段，未展开为全文",
  domainSummary: "领域概要",
  noSummary: "暂无概要。",
  prerequisites: "前置领域",
  researchBranches: "研究分支",
  supportingCitations: "支持论文引用",
  citationDisclaimer:
    "以下是支持关系可追溯的论文元数据，不代表工具读取或引用了全文/原文。",
  readingStart: "阅读起点（当前排序前 3）",
  otherCorePapers: "其他核心论文",
  currentLimitations: "当前限制",
  loadedFields: "已加载领域",
  noTraceablePapers: "未返回可追溯支持论文元数据。",
  incompleteNotice:
    "当前结果只到 {phase} 阶段；以下只列出已返回的数据，不补写未生成的分支或论文判断。",
  invalidResult: "结果字段无效，未生成可引用内容。",
  heuristicLimit: "排序只在本次候选集内比较（heuristic），不是系统综述。",
  confidenceLimit: "置信度未校准，不能替代人工核验。",
  metadataLimit: "论文条目是可追溯的元数据，不等同于全文或原文引用。",
  evidenceLimit: "证据层级由标题/摘要字段自动核对；短摘录不是全文验证。",
  maturityLimit: "关系成熟度表示文献覆盖层级，不代表全文验证或机制定论。",
  candidateRange: (candidate, analyzed) =>
    analyzed === null
      ? `${candidate} 篇候选论文`
      : `${candidate} 篇候选论文，分析了 ${analyzed} 篇`,
  candidateScore: (value) => `候选集评分 ${value}`,
  confidence: (value) => `置信度 ${value}`,
  evidence: (value) => `证据层级：${value}`,
  maturity: (value) => `成熟度：${value}`,
  evidenceMetadata: (value) => `证据元数据：${value}`,
  excerpt: (source, value) => `${source}摘录：“${value}”`,
  phase: (value) => `${value} 阶段`,
  sourceSummary: (paper, analysis) => `${paper}；${analysis}`,
};

const EN: ExportLabels = {
  product: "Field Navigator",
  readingList: "Reading list",
  exportedAt: "Exported at",
  toRead: "To read",
  read: "Read",
  authors: "Authors",
  year: "Year",
  journal: "Journal",
  doi: "DOI",
  fields: "Fields",
  reason: "Recommendation",
  note: "Personal notes",
  savedAt: "Saved at",
  empty: "The list is empty.",
  source: "Source",
  demoData: "demo data",
  llmAnalysis: "LLM analysis",
  mockAnalysis: "mock analysis",
  pendingAnalysis: "Pending analysis",
  candidatePapers: "candidate papers",
  analyzedPapers: "analysed",
  unknown: "Unknown",
  supported: "Abstract-supported · auto-checked",
  weak: "Limited evidence",
  toVerify: "To verify",
  researchDirection: "Literature-covered direction",
  theoryCandidate: "Theory / candidate explanation",
  titleOnly: "Title-only clue",
  abstractEvidence: "Abstract evidence",
  titleClue: "Title clue",
  primary: "Primary research",
  review: "Review / guide",
  background: "Background",
  nonResearch: "Non-research item",
  roleToVerify: "Role to verify",
  metadataIncomplete: "Incomplete metadata",
  abstractMetadata: "Abstract is metadata only; full text was not expanded",
  domainSummary: "Field summary",
  noSummary: "No summary available.",
  prerequisites: "Prerequisite fields",
  researchBranches: "Research branches",
  supportingCitations: "Supporting paper references",
  citationDisclaimer:
    "These are traceable paper metadata supporting the relations; the tool did not read or quote the full text.",
  readingStart: "Reading start (top 3 by current ranking)",
  otherCorePapers: "Other core papers",
  currentLimitations: "Current limitations",
  loadedFields: "Loaded fields",
  noTraceablePapers: "No traceable supporting paper metadata was returned.",
  incompleteNotice:
    "The result reached only the {phase} phase; only returned data is listed below, with no generated branches or paper judgments filled in.",
  invalidResult:
    "The field result is invalid; no citable content was generated.",
  heuristicLimit:
    "Ranking compares papers only within this candidate set (heuristic), not a systematic review.",
  confidenceLimit:
    "Confidence is not calibrated and cannot replace human review.",
  metadataLimit:
    "Paper entries are traceable metadata, not full-text access or quotations.",
  evidenceLimit:
    "Evidence levels are checked automatically from title/abstract fields; short excerpts are not full-text verification.",
  maturityLimit:
    "Relation maturity describes literature coverage, not full-text verification or a settled mechanism.",
  candidateRange: (candidate, analyzed) =>
    analyzed === null
      ? `${candidate} candidate papers`
      : `${candidate} candidate papers; ${analyzed} analysed`,
  candidateScore: (value) => `candidate-set score ${value}`,
  confidence: (value) => `confidence ${value}`,
  evidence: (value) => `evidence level: ${value}`,
  maturity: (value) => `maturity: ${value}`,
  evidenceMetadata: (value) => `evidence metadata: ${value}`,
  excerpt: (source, value) => `${source} excerpt: “${value}”`,
  phase: (value) => `${value} phase`,
  sourceSummary: (paper, analysis) => `${paper}; ${analysis}`,
};

export function exportLabels(language: Language = "zh-CN"): ExportLabels {
  return normalizeLanguage(language) === "en" ? EN : ZH;
}

/** Keep user-provided timestamps stable while localizing their surrounding label. */
export function exportDate(value: string): string {
  return value || "";
}
