import { ArrowRight, BookOpen, Compass, MessageCircle, X } from "lucide-react";
import type { QueryCandidate, QueryResolution } from "../types";

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

export function DirectionChooser({
  resolution,
  onChoose,
  onDismiss,
}: {
  resolution: QueryResolution;
  onChoose: (candidate: QueryCandidate) => void;
  onDismiss: () => void;
}) {
  return (
    <section className="direction-panel" aria-labelledby="direction-title">
      <div className="direction-heading">
        <div>
          <span className="eyebrow">
            <Compass size={14} /> 确认研究范围
          </span>
          <h2 id="direction-title">
            {resolution.status === "clarify"
              ? "再补充一点背景，会更准确"
              : "哪一个方向更接近你的问题？"}
          </h2>
        </div>
        <button
          className="icon-button"
          onClick={onDismiss}
          aria-label="关闭方向选择"
        >
          <X size={19} />
        </button>
      </div>
      <p>{resolution.message}</p>
      {resolution.status === "clarify" ? (
        <div className="clarify-hint">
          <MessageCircle size={19} />
          <div>
            <strong>可以补充材料、现象或你想解决的问题</strong>
            <p>
              例如把“KTO”写成“KTaO₃
              氧化物界面的超导，想了解相关研究方向”。也可以输入明确的英文领域名称。
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="direction-candidates">
            {resolution.candidates.map((candidate, index) => (
              <article key={candidate.query} className="direction-card">
                <span className="candidate-number">
                  方向 {String(index + 1).padStart(2, "0")}
                </span>
                <h3>{candidate.name}</h3>
                <span className="candidate-query">{candidate.query}</span>
                <p>{candidate.summary}</p>
                <div className="candidate-evidence">
                  <span>
                    <BookOpen size={12} />{" "}
                    {candidate.evidence_papers.length
                      ? "检索匹配论文"
                      : "直接关键词检索"}
                  </span>
                  {candidate.evidence_papers.slice(0, 2).map((paper) => (
                    <div key={paper.id}>
                      {safeLink(paper.url) ? (
                        <a
                          href={safeLink(paper.url)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {paper.title}
                        </a>
                      ) : (
                        <span>{paper.title}</span>
                      )}
                      <small>{paper.year ?? "年份未提供"}</small>
                    </div>
                  ))}
                </div>
                <button className="primary" onClick={() => onChoose(candidate)}>
                  用这个方向构建地图
                  <ArrowRight size={15} />
                </button>
              </article>
            ))}
          </div>
          <p className="direction-note">
            方向是分析建议，论文匹配不等于原文已经证实该范围。请按你的研究意图选择；不合适时可改写问题。
          </p>
        </>
      )}
    </section>
  );
}
