import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  GitBranch,
  Layers,
} from "lucide-react";
import type { FieldNode, FieldRelation, Paper } from "../types";
import { abstractProvenanceLabel } from "../state/provenance";

function evidenceStatus(relation: FieldRelation) {
  if (relation.evidence_status === "supported")
    return { label: "摘要支持 · 自动核对", className: "supported" };
  if (relation.evidence_status === "weak")
    return { label: "线索有限", className: "weak" };
  return { label: "待核对", className: "unverified" };
}

function claimLevel(relation: FieldRelation) {
  if (relation.claim_level === "theory_or_proposed")
    return {
      label: "理论 / 候选解释",
      className: "theory",
      title:
        "文献覆盖该研究方向，但这里是理论或候选解释，不代表全文验证或机制定论",
    };
  if (relation.claim_level === "title_only")
    return {
      label: "仅题名线索",
      className: "title-only",
      title: "目前只有题名级线索，不能确认研究方向，更不能确认机制",
    };
  return {
    label: "文献覆盖方向",
    className: "direction",
    title: "有文献覆盖该研究方向；不代表全文验证或机制定论",
  };
}

function shortText(value: string, limit = 260) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function safeLink(url: string | null) {
  try {
    const parsed = new URL(url || "");
    return ["https:", "http:"].includes(parsed.protocol)
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function RelationEvidenceList({
  field,
  kind,
  minConfidence,
  onExplore,
}: {
  field: FieldNode;
  kind: "subfields" | "prerequisites";
  minConfidence: number;
  onExplore: (name: string) => void;
}) {
  const relations = field[kind].filter(
    (relation) => relation.confidence >= minConfidence,
  );
  const evidence = new Map<string, Paper>(
    [
      ...field.core_papers.map((core) => core.paper),
      ...(field.evidence_papers ?? []),
    ].map((paper) => [paper.id, paper]),
  );
  function sources(relation: FieldRelation) {
    return relation.evidence_paper_ids
      .map((id) => evidence.get(id))
      .filter((paper): paper is Paper => Boolean(paper));
  }
  return (
    <div className="relation-evidence-list">
      {relations.length ? (
        relations.map((relation) => (
          <article className="relation-evidence-card" key={relation.name}>
            <div className="relation-card-title">
              <span
                className={`relation-kind ${kind === "subfields" ? "branch" : "pre"}`}
              >
                {kind === "subfields" ? (
                  <GitBranch size={15} />
                ) : (
                  <Layers size={15} />
                )}
              </span>
              <h3>{relation.name}</h3>
              <small>
                {field.analysis_source === "mock"
                  ? "预设示例关系"
                  : "模型推断关系"}
              </small>
              {field.analysis_source !== "mock" && (
                <span
                  className={`evidence-status ${evidenceStatus(relation).className}`}
                  title="自动核对只说明文献与研究方向相关；不代表全文验证或机制定论"
                >
                  {evidenceStatus(relation).label}
                </span>
              )}
              <span
                className={`claim-level-badge ${claimLevel(relation).className}`}
                title={claimLevel(relation).title}
              >
                {claimLevel(relation).label}
              </span>
            </div>
            <p>{relation.reason}</p>
            <div className="relation-card-actions">
              <details className="relation-evidence-details">
                <summary>
                  <BookOpen size={13} />
                  {relation.evidence_paper_ids.length} 篇支持书目
                  <ChevronDown size={13} />
                </summary>
                <div>
                  {sources(relation).length ? (
                    sources(relation).map((paper) => (
                      <div className="relation-source" key={paper.id}>
                        {safeLink(paper.url) ? (
                          <a
                            href={safeLink(paper.url)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {paper.title}
                            <ArrowUpRight size={12} />
                          </a>
                        ) : (
                          <span>{paper.title}</span>
                        )}
                        <small>
                          {paper.year ?? "年份未知"} ·{" "}
                          {paper.journal || "来源未提供"}
                        </small>
                        {(() => {
                          const quotes = (relation.evidence_quotes ?? [])
                            .filter((quote) => quote.paper_id === paper.id)
                            .slice(0, 2);
                          if (quotes.length)
                            return quotes.map((quote, index) => (
                              <p
                                className="evidence-quote"
                                key={`${paper.id}:quote:${index}`}
                              >
                                <span>
                                  {quote.source === "abstract"
                                    ? "摘要摘录"
                                    : "标题线索"}
                                </span>
                                “{shortText(quote.quote)}”
                              </p>
                            ));
                          return paper.abstract ? (
                            <>
                              <p className="evidence-quote evidence-quote-unverified">
                                <span>摘要元数据摘录 · 待核对</span>“
                                {shortText(paper.abstract)}”
                              </p>
                              {paper.abstract_source_record_id &&
                                paper.abstract_source_record_id !==
                                  paper.id && (
                                  <small className="evidence-provenance-note">
                                    {abstractProvenanceLabel(paper)}
                                  </small>
                                )}
                            </>
                          ) : (
                            <p className="evidence-quote evidence-quote-unverified">
                              <span>暂无摘要证据</span>
                              这条书目只能作为检索线索，不能确证该关系。
                            </p>
                          );
                        })()}
                        {paper.abstract_source_record_id &&
                          paper.abstract_source_record_id !== paper.id &&
                          relation.evidence_quotes?.some(
                            (quote) =>
                              quote.paper_id === paper.id &&
                              quote.source === "abstract",
                          ) && (
                            <small className="evidence-provenance-note">
                              {abstractProvenanceLabel(paper)}
                            </small>
                          )}
                      </div>
                    ))
                  ) : (
                    <p>
                      当前记录未保存完整支持书目；可以重新分析补充。模型关系仍需核对原文。
                    </p>
                  )}
                  <p className="evidence-boundary">
                    自动核对只说明标题/摘要与该研究方向相关；没有全文验证，也不等于机制定论。
                    {relation.evidence_warnings?.length
                      ? ` ${relation.evidence_warnings.join(" ")}`
                      : ""}
                  </p>
                </div>
              </details>
              <button
                className="text-button"
                onClick={() => onExplore(relation.name)}
              >
                探索这个方向
                <ArrowRight size={14} />
              </button>
            </div>
          </article>
        ))
      ) : (
        <div className="empty-relations">
          <BookOpen size={26} />
          <h3>
            {field.phase !== "complete"
              ? "可以先从已有论文开始"
              : "当前没有符合筛选条件的关系"}
          </h3>
          <p>
            {field.phase !== "complete"
              ? "领域分析尚未完成。论文出处和收藏功能仍可使用。"
              : "减少筛选强度，或尝试更明确的研究范围；没有依据时不会补造研究分支。"}
          </p>
        </div>
      )}
    </div>
  );
}
