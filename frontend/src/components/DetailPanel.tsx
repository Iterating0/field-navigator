import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  ExternalLink,
  FileText,
  Info,
} from "lucide-react";
import type { FieldNode, FieldRelation, Paper } from "../types";
function safeUrl(url: string | null) {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}
const signalNames: Record<string, string> = {
  relevance: "领域相关度",
  citation: "引用量",
  age_normalized: "年限归一化",
  shared_references: "候选集引用",
  llm_importance: "核心性判断",
};
export function DetailPanel({
  field,
  onExplore,
  busy,
}: {
  field: FieldNode;
  onExplore: (name: string) => void;
  busy: boolean;
}) {
  const [tab, setTab] = useState<"papers" | "overview">("papers");
  useEffect(() => {
    document.querySelector(".detail-scroll")?.scrollTo(0, 0);
  }, [field.id, tab]);
  const evidenceById = new Map(
    (field.evidence_papers ?? []).map((paper) => [paper.id, paper]),
  );
  const evidenceFor = (relation: FieldRelation) =>
    relation.evidence_paper_ids
      .map((id) => evidenceById.get(id))
      .filter((paper): paper is Paper => Boolean(paper));
  const relations = (label: string, items: FieldRelation[]) => (
    <section className="overview-section">
      <h3>
        {label} <small>{items.length}</small>
      </h3>
      {items.length ? (
        items.map((r) => {
          const evidence = evidenceFor(r);
          return (
            <div key={r.name}>
              <button
                className="relation-detail"
                disabled={busy}
                onClick={() => onExplore(r.name)}
              >
                <strong>
                  {r.name}
                  <ArrowUpRight size={15} />
                </strong>
                <span>{r.reason}</span>
                <small>
                  {field.analysis_source === "mock"
                    ? "演示置信度"
                    : "模型置信度"}{" "}
                  {Math.round(r.confidence * 100)}% ·{" "}
                  {r.evidence_paper_ids.length} 篇证据论文
                </small>
              </button>
              {r.evidence_paper_ids.length > 0 && (
                <details className="why-core">
                  <summary>
                    <span>
                      <BookOpen size={12} />
                      查看支持论文（{r.evidence_paper_ids.length}）
                    </span>
                    <ChevronDown size={13} />
                  </summary>
                  {evidence.length > 0 ? (
                    evidence.map((paper) => {
                      const url = safeUrl(paper.url);
                      return (
                        <p key={paper.id}>
                          {url ? (
                            <a
                              className="paper-title"
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {paper.title}
                              <ArrowUpRight size={13} />
                            </a>
                          ) : (
                            <span>{paper.title}</span>
                          )}
                          <small>
                            {paper.year ?? "年份未知"} ·{" "}
                            {paper.journal || "来源未提供"}
                          </small>
                        </p>
                      );
                    })
                  ) : (
                    <p>
                      旧缓存只保存了证据 ID；重新分析后可加载论文标题和链接。
                    </p>
                  )}
                </details>
              )}
            </div>
          );
        })
      ) : (
        <p className="muted">当前分析没有给出更多关系。</p>
      )}
    </section>
  );
  return (
    <aside className="detail-panel">
      <div className="detail-top">
        <span className="eyebrow">
          <BookOpen size={14} />
          FIELD NOTES
        </span>
        <h2>从领域到文献</h2>
        <p>理解脉络，再选择值得读的论文。</p>
      </div>
      <div className="detail-tabs" role="tablist" aria-label="领域详情">
        <button
          role="tab"
          aria-selected={tab === "papers"}
          className={tab === "papers" ? "active" : ""}
          onClick={() => setTab("papers")}
        >
          {field.phase === "complete" ? "核心论文" : "初筛论文"}{" "}
          <span>{field.core_papers.length}</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "overview"}
          className={tab === "overview" ? "active" : ""}
          onClick={() => setTab("overview")}
        >
          领域概览
        </button>
      </div>
      <div className="detail-scroll" role="tabpanel">
        {tab === "papers" ? (
          <>
            <div className="reading-caption">
              <span>
                {field.phase === "complete"
                  ? "建议阅读入口"
                  : "模型评价尚未完成"}
              </span>
              <span>
                按综合得分排序 <Info size={12} />
              </span>
            </div>
            {field.core_papers.map((core, index) => (
              <article
                className="paper-card"
                key={`${field.id}:${core.paper.id}`}
              >
                <div className="paper-index">
                  {String(index + 1).padStart(2, "0")}
                </div>
                <div className="paper-content">
                  <div className="paper-meta">
                    <span>{core.paper.year ?? "年份未知"}</span>
                    <span
                      className="paper-score"
                      title="候选集内综合得分，不代表客观重要性或概率"
                    >
                      {Math.round(core.score * 100)} 分
                    </span>
                  </div>
                  <a
                    className="paper-title"
                    href={safeUrl(core.paper.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {core.paper.title}
                    <ArrowUpRight size={14} />
                  </a>
                  <p className="authors">
                    {core.paper.authors.slice(0, 2).join(", ")}
                    {core.paper.authors.length > 2 ? " et al." : ""}
                  </p>
                  <p className="journal">
                    {core.paper.journal || "来源未提供"}
                    {core.paper.citation_count !== null && (
                      <> · {core.paper.citation_count.toLocaleString()} 引用</>
                    )}
                  </p>
                  <details className="why-core" open={index === 0}>
                    <summary>
                      <span>
                        <FileText size={12} />
                        为什么读这篇
                      </span>
                      <ChevronDown size={13} />
                    </summary>
                    <p>{core.reason}</p>
                    <div className="signal-list">
                      {Object.entries(core.signals).map(([key, value]) => (
                        <div key={key}>
                          <span>
                            {key === "llm_importance" &&
                            field.analysis_source === "mock"
                              ? "演示优先级"
                              : (signalNames[key] ?? key)}
                          </span>
                          <meter min="0" max="1" value={value} />
                          <b>{Math.round(value * 100)}</b>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              </article>
            ))}
            <p className="paper-note">
              评分用于候选集内比较。领域关系和阅读建议需结合原文判断。
            </p>
          </>
        ) : (
          <>
            <section className="overview-section">
              <span className="eyebrow">CURRENT FIELD</span>
              <h3>{field.name}</h3>
              <p>{field.summary}</p>
            </section>
            {relations("前置领域", field.prerequisites)}
            {relations("研究分支", field.subfields)}
            <section className="overview-section source-notes">
              <h3>分析来源</h3>
              <p>
                论文：
                {field.paper_source === "demo"
                  ? "离线演示书目"
                  : "OpenAlex 实时检索"}
                <br />
                拆分：
                {field.analysis_source === "pending"
                  ? "正在分析"
                  : field.analysis_source === "mock"
                    ? "预设演示"
                    : "LLM 结构化分析"}
                <br />
                生成时间：{new Date(field.created_at).toLocaleString("zh-CN")}
              </p>
              {field.warnings.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </section>
          </>
        )}
      </div>
      <div className="detail-bottom">
        <ExternalLink size={12} />
        点击论文标题，在来源页面继续阅读
      </div>
    </aside>
  );
}
