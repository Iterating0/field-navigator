import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Bookmark,
  Compass,
  GitBranch,
  Play,
  Sparkles,
} from "lucide-react";
import { SearchBar } from "./SearchBar";
import type { Mode } from "../types";

interface Props {
  query: string;
  setQuery: (query: string) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  resolving: boolean;
  onSearch: () => void;
  onDemo: () => void;
  onContinue?: () => void;
  previousName?: string;
  savedCount: number;
  onLibrary: () => void;
}

export function ResearchStart(props: Props) {
  const examples = [
    "我想入门二维电子气，先读哪些论文？",
    "KTO 界面超导属于哪些研究方向？",
    "氧化物界面超导",
  ];
  return (
    <div className="research-start">
      <div className="start-kicker">
        <span className="status-dot" /> 从一个问题开始，一步步找到方向
      </div>
      <section className="start-hero">
        <div className="start-copy">
          <h1>
            研究的第一步，
            <br />
            <em>可以更清晰。</em>
          </h1>
          <p>
            理清一个领域的脉络，找到有来源的论文，
            <br className="desktop-break" />
            把“接下来读什么”变成自己的阅读清单。
          </p>
          <div className="hero-proof">
            <BookOpen size={15} /> 论文来源可查 <span /> <GitBranch size={15} />{" "}
            关系依据可看 <span /> <Bookmark size={15} /> 阅读进度可保存
          </div>
        </div>
        <button
          className="map-preview"
          onClick={props.onDemo}
          aria-label="体验非厄米趋肤效应离线示例"
        >
          <div className="preview-caption">
            <span>
              <Compass size={14} /> 一张地图，一条阅读路径
            </span>
            <ArrowUpRight size={17} />
          </div>
          <div className="preview-canvas" aria-hidden="true">
            <svg viewBox="0 0 440 235" preserveAspectRatio="none">
              <path d="M90 68 C165 68 150 119 210 119 M90 178 C165 178 150 119 210 119 M210 119 C278 119 281 50 350 50 M210 119 C278 119 281 125 350 125 M210 119 C278 119 281 204 350 204" />
            </svg>
            <span className="preview-node preview-pre top">
              非厄米物理<small>前置概念</small>
            </span>
            <span className="preview-node preview-pre bottom">
              拓扑与能带<small>前置概念</small>
            </span>
            <span className="preview-node preview-center">
              <Compass size={18} /> NHSE<small>示例研究主题</small>
            </span>
            <span className="preview-node preview-branch first">
              研究分支<small>继续探索</small>
            </span>
            <span className="preview-node preview-branch second">
              支持论文<small>查看出处</small>
            </span>
            <span className="preview-node preview-branch third">
              阅读起点<small>保存到清单</small>
            </span>
          </div>
          <div className="preview-footer">
            <span>示意预览 · 点击打开已核对书目的离线示例</span>
            <Play size={13} />
          </div>
        </button>
      </section>
      <section className="start-search" aria-labelledby="start-search-title">
        <div className="start-search-label">
          <h2 id="start-search-title">你想弄清楚什么？</h2>
          <span>领域名称、简称，或一个中文问题</span>
        </div>
        <SearchBar
          query={props.query}
          setQuery={props.setQuery}
          mode={props.mode}
          setMode={props.setMode}
          busy={props.resolving}
          onSearch={props.onSearch}
          variant="hero"
        />
        <div className="query-examples">
          <span>试试</span>
          {examples.map((example) => (
            <button
              key={example}
              onClick={() => {
                props.setQuery(example);
                if (props.mode === "demo") props.setMode("auto");
                document
                  .querySelector<HTMLInputElement>(
                    '[aria-label="搜索科研领域"]',
                  )
                  ?.focus();
              }}
            >
              {example}
              <ArrowUpRight size={12} />
            </button>
          ))}
        </div>
        <p className="start-search-note">
          中文和模糊问题会先识别可能方向；需要选择时，由你决定探索范围。实时检索会将研究问题发送给论文检索和分析服务。
        </p>
      </section>
      <section className="start-steps" aria-label="研究工作流程">
        <article>
          <span className="step-number">01</span>
          <div>
            <h3>把问题变成方向</h3>
            <p>确认检索范围，再开始探索。减少简称和宽泛问题带来的偏题。</p>
          </div>
          <Compass size={21} />
        </article>
        <article>
          <span className="step-number">02</span>
          <div>
            <h3>看懂地图，核对依据</h3>
            <p>在前置知识与研究分支之间导航，直接查看关系对应的论文。</p>
          </div>
          <GitBranch size={21} />
        </article>
        <article>
          <span className="step-number">03</span>
          <div>
            <h3>带走可以继续的研究</h3>
            <p>收藏论文、标记已读、留下笔记，导出一份带来源的研究简报。</p>
          </div>
          <BookOpen size={21} />
        </article>
      </section>
      <div className="start-bottom">
        <button className="start-demo" onClick={props.onDemo}>
          <Play size={14} />
          <span>先用离线示例体验</span>
          <small>无需等待外部服务</small>
          <ArrowRight size={15} />
        </button>
        {props.onContinue && props.previousName ? (
          <button className="resume-research" onClick={props.onContinue}>
            <Sparkles size={14} />
            <span>继续：{props.previousName}</span>
            <ArrowRight size={15} />
          </button>
        ) : props.savedCount > 0 ? (
          <button className="resume-research" onClick={props.onLibrary}>
            <Bookmark size={14} />
            查看 {props.savedCount} 篇已收藏论文
            <ArrowRight size={15} />
          </button>
        ) : (
          <span className="quiet-note">研究记录与笔记只保存在当前浏览器</span>
        )}
      </div>
    </div>
  );
}
