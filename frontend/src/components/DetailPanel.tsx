import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Bookmark,
  BookOpen,
  Check,
  ChevronDown,
  ExternalLink,
  FileText,
  Info,
} from "lucide-react";
import { isSavedPaper, safeHttpUrl } from "../state/library";
import { abstractProvenanceLabel } from "../state/provenance";
import type { CorePaper, FieldNode, FieldRelation, Paper } from "../types";
import "./library.css";

function shortText(value: string, limit = 260) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

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

function basisLabel(value: CorePaper["evidence_basis"]) {
  if (value === "abstract") return "摘要证据";
  if (value === "title") return "标题线索";
  return "待核对";
}

function roleLabel(value: CorePaper["role"]) {
  if (value === "primary") return "原始研究";
  if (value === "review") return "综述导读";
  if (value === "background") return "背景材料";
  if (value === "non_research") return "非研究条目";
  return "角色待核对";
}
function safeUrl(url: string | null) {
  return safeHttpUrl(url);
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
  onSavePaper,
  savedPaperIds,
}: {
  field: FieldNode;
  onExplore: (name: string) => void;
  busy: boolean;
  onSavePaper?: (core: CorePaper, fieldName: string) => void;
  savedPaperIds?: string[];
}) {
  const [tab, setTab] = useState<"papers" | "overview">("papers");
  useEffect(() => {
    document.querySelector(".detail-scroll")?.scrollTo(0, 0);
  }, [field.id, tab]);
  const evidenceById = new Map(
    [
      ...field.core_papers.map((core) => core.paper),
      ...(field.evidence_papers ?? []),
    ].map((paper) => [paper.id, paper]),
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
                {field.analysis_source !== "mock" && (
                  <em
                    className={`evidence-status ${evidenceStatus(r).className}`}
                    title="自动核对只说明文献与研究方向相关；不代表全文验证或机制定论"
                  >
                    {evidenceStatus(r).label}
                  </em>
                )}
                <span
                  className={`claim-level-badge ${claimLevel(r).className}`}
                  title={claimLevel(r).title}
                >
                  {claimLevel(r).label}
                </span>
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
                          {r.evidence_quotes
                            ?.filter((quote) => quote.paper_id === paper.id)
                            .slice(0, 2)
                            .map((quote, index) => (
                              <span
                                className="evidence-quote"
                                key={`${paper.id}:relation-quote:${index}`}
                              >
                                <b>
                                  {quote.source === "abstract"
                                    ? "摘要摘录"
                                    : "标题线索"}
                                </b>
                                “{shortText(quote.quote)}”
                              </span>
                            ))}
                          {!r.evidence_quotes?.some(
                            (quote) => quote.paper_id === paper.id,
                          ) &&
                            paper.abstract && (
                              <>
                                <span className="evidence-quote evidence-quote-unverified">
                                  <b>摘要元数据摘录 · 待核对</b>“
                                  {shortText(paper.abstract)}”
                                </span>
                                {paper.abstract_source_record_id &&
                                  paper.abstract_source_record_id !==
                                    paper.id && (
                                    <small className="evidence-provenance-note">
                                      {abstractProvenanceLabel(paper)}
                                    </small>
                                  )}
                              </>
                            )}
                          {paper.abstract_source_record_id &&
                            paper.abstract_source_record_id !== paper.id &&
                            r.evidence_quotes?.some(
                              (quote) =>
                                quote.paper_id === paper.id &&
                                quote.source === "abstract",
                            ) && (
                              <small className="evidence-provenance-note">
                                {abstractProvenanceLabel(paper)}
                              </small>
                            )}
                        </p>
                      );
                    })
                  ) : (
                    <p>
                      旧缓存只保存了证据 ID；重新分析后可加载论文标题和链接。
                    </p>
                  )}
                  <p className="evidence-boundary">
                    自动核对只说明标题/摘要与该研究方向相关；没有全文验证，也不等于机制定论。
                    {r.evidence_warnings?.length
                      ? ` ${r.evidence_warnings.join(" ")}`
                      : ""}
                  </p>
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
            {field.core_papers.map((core, index) => {
              const url = safeUrl(core.paper.url);
              const abstract = (
                core.paper as Paper & { abstract?: string | null }
              ).abstract?.trim();
              const saved = isSavedPaper(core.paper, savedPaperIds);
              return (
                <article
                  className="paper-card"
                  key={`${field.id}:${core.paper.id}`}
                >
                  <div className="paper-index">
                    {String(index + 1).padStart(2, "0")}
                  </div>
                  <div className="paper-content">
                    <div className="paper-meta">
                      <span className="paper-meta-left">
                        <span>{core.paper.year ?? "年份未知"}</span>
                        <span
                          className={`paper-quality-badge ${core.evidence_basis === "abstract" ? "supported" : core.evidence_basis === "title" ? "weak" : "unverified"}`}
                          title="自动核对只说明文献与研究方向相关；不代表全文验证或机制定论"
                        >
                          {basisLabel(core.evidence_basis)}
                        </span>
                        {core.role && (
                          <span
                            className={`paper-role-badge ${core.role === "non_research" ? "warning" : ""}`}
                          >
                            {roleLabel(core.role)}
                          </span>
                        )}
                      </span>
                      <span
                        className="paper-score"
                        title="候选集内综合得分，不代表客观重要性或概率"
                      >
                        {Math.round(core.score * 100)} 分
                      </span>
                    </div>
                    <div className="paper-title-row">
                      {url ? (
                        <a
                          className="paper-title"
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {core.paper.title}
                          <ArrowUpRight size={14} />
                        </a>
                      ) : (
                        <span className="paper-title paper-title-unavailable">
                          {core.paper.title}
                        </span>
                      )}
                      {onSavePaper && (
                        <button
                          type="button"
                          className={`paper-save-button ${saved ? "saved" : ""}`}
                          aria-pressed={saved}
                          aria-label={
                            saved
                              ? `已在阅读清单，可补充${field.name}来源`
                              : `加入阅读清单：${core.paper.title}`
                          }
                          title={
                            saved
                              ? "再次点击会合并当前领域的推荐理由"
                              : "加入阅读清单"
                          }
                          onClick={() => onSavePaper(core, field.name)}
                        >
                          {saved ? <Check size={14} /> : <Bookmark size={14} />}
                          {saved ? "已在清单" : "加入清单"}
                        </button>
                      )}
                    </div>
                    {!url && (
                      <p className="paper-link-note">暂无可用来源链接</p>
                    )}
                    <p className="authors">
                      {core.paper.authors.slice(0, 2).join(", ")}
                      {core.paper.authors.length > 2 ? " et al." : ""}
                    </p>
                    <p className="journal">
                      {core.paper.journal || "来源未提供"}
                      {core.paper.citation_count !== null && (
                        <>
                          {" "}
                          · {core.paper.citation_count.toLocaleString()} 引用
                        </>
                      )}
                    </p>
                    {abstract && (
                      <details className="why-core paper-abstract">
                        <summary>
                          <span>
                            <BookOpen size={12} />
                            查看摘要摘录
                          </span>
                          <ChevronDown size={13} />
                        </summary>
                        <p>{shortText(abstract, 360)}</p>
                      </details>
                    )}
                    {core.evidence_quote && (
                      <>
                        <p className="paper-evidence-quote">
                          <b>
                            {core.evidence_basis === "title"
                              ? "标题线索"
                              : "摘要摘录"}
                          </b>
                          “{shortText(core.evidence_quote)}”
                        </p>
                        {core.evidence_basis === "abstract" &&
                          core.paper.abstract_source_record_id &&
                          core.paper.abstract_source_record_id !==
                            core.paper.id && (
                            <small className="evidence-provenance-note">
                              {abstractProvenanceLabel(core.paper)}
                            </small>
                          )}
                      </>
                    )}
                    {!abstract && !core.evidence_quote && (
                      <p className="paper-evidence-warning">
                        暂无标题/摘要证据，仅作为检索线索，不能确证贡献。
                      </p>
                    )}
                    {core.role === "non_research" && (
                      <p className="paper-evidence-warning">
                        该记录被标为非研究条目，仅供定位来源，不计为原始研究证据。
                      </p>
                    )}
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
              );
            })}
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
                  ? busy
                    ? "正在分析"
                    : "模型分析未完成"
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
        {field.core_papers.some((core) => safeUrl(core.paper.url))
          ? "点击有来源链接的论文标题，在原文页面继续阅读"
          : "当前论文没有可用的来源链接"}
      </div>
    </aside>
  );
}
