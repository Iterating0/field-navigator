import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  Compass,
  Database,
  Download,
  FlaskConical,
  GitBranch,
  History,
  Info,
  Layers,
  LoaderCircle,
  Moon,
  Network,
  Plus,
  RotateCw,
  Settings2,
  Sun,
  X,
} from "lucide-react";
import { exploreField } from "./api/client";
import { ExplorationRequests, requestKey } from "./state/exploration";
import { DetailPanel } from "./components/DetailPanel";
import { FieldGraph, keyOf } from "./components/FieldGraph";
import { SearchBar } from "./components/SearchBar";
import type { FieldNode, Mode } from "./types";
const ROOT = "Non-Hermitian Skin Effect";
type HistoryEntry = { name: string; parent: string | null };
function storedSession(): {
  history: HistoryEntry[];
  current: string;
  mode: Mode;
} {
  try {
    const saved = JSON.parse(
      localStorage.getItem("field-navigator-session-v1") || "null",
    );
    if (
      saved &&
      ["auto", "demo", "live"].includes(saved.mode) &&
      typeof saved.current === "string" &&
      Array.isArray(saved.history)
    )
      return {
        ...saved,
        history: saved.history
          .filter((h: HistoryEntry) => typeof h?.name === "string")
          .slice(-50),
      };
  } catch {
    /* Private browsing may disable storage. */
  }
  return { history: [], current: ROOT, mode: "auto" };
}
export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#111923" : "#ffffff");
    try {
      localStorage.setItem("field-navigator-theme", theme);
    } catch {
      // Theme switching still works when browser storage is unavailable.
    }
  }, [theme]);
  const [initial] = useState(storedSession);
  const [showTable, setShowTable] = useState(() => window.innerHeight >= 850);
  const failedMode = useRef<Mode>(initial.mode);
  const failedRefresh = useRef(false);
  const [exportContent, setExportContent] = useState("");
  const exportUrl = useMemo(
    () =>
      exportContent
        ? URL.createObjectURL(
            new Blob([exportContent], { type: "application/json" }),
          )
        : "",
    [exportContent],
  );
  useEffect(
    () => () => {
      if (exportUrl) URL.revokeObjectURL(exportUrl);
    },
    [exportUrl],
  );
  const [query, setQuery] = useState(initial.current),
    [mode, setMode] = useState<Mode>(initial.mode);
  const [field, setField] = useState<FieldNode | null>(null),
    [explored, setExplored] = useState<Record<string, FieldNode>>({});
  const [history, setHistory] = useState<HistoryEntry[]>(initial.history),
    [trail, setTrail] = useState<string[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [loadingName, setLoadingName] = useState("");
  const [loadingStage, setLoadingStage] = useState("正在检查缓存…");
  const [requests] = useState(() => new ExplorationRequests(exploreField));
  const [pending, setPending] = useState<
    Record<string, { name: string; mode: Mode }>
  >({});
  const activeRequest = useRef("");
  const completedMode = useRef<Mode>(initial.mode);
  const displayed = useRef<FieldNode | null>(null);
  const [backgroundErrors, setBackgroundErrors] = useState<
    Record<string, { name: string; mode: Mode; error: string }>
  >({});
  const [showHelp, setShowHelp] = useState(false),
    [showPrerequisites, setShowPrerequisites] = useState(true),
    [showSubfields, setShowSubfields] = useState(true);
  const [depth, setDepth] = useState(1),
    [minConfidence, setMinConfidence] = useState(0),
    [relationTab, setRelationTab] = useState<"subfields" | "prerequisites">(
      "subfields",
    );
  const [health, setHealth] = useState<{
    llm_configured?: boolean;
    llm_ready?: boolean;
    openalex_key_configured: boolean;
  } | null>(null);
  const modeRef = useRef(mode),
    currentRef = useRef<FieldNode | null>(null),
    started = useRef(false);
  const explore = useCallback(
    async (
      name: string,
      options: { refresh?: boolean; resetPath?: boolean; mode?: Mode } = {},
    ) => {
      const selectedMode = options.mode ?? modeRef.current;
      const ticket = requests.select();
      const key = requestKey(name, selectedMode);
      activeRequest.current = key;
      const changedMode = selectedMode !== modeRef.current;
      modeRef.current = selectedMode;
      setMode(selectedMode);
      if (changedMode) setExplored({});
      failedMode.current = selectedMode;
      failedRefresh.current = !!options.refresh;
      setBusy(true);
      setPending((old) => ({ ...old, [key]: { name, mode: selectedMode } }));
      setError("");
      setLoadingName(name);
      setLoadingStage("正在检查缓存…");
      const previous = currentRef.current;
      const previousMode = completedMode.current;
      const parent = options.resetPath
        ? null
        : (displayed.current?.name ?? null);
      setBackgroundErrors((old) => {
        const next = { ...old };
        delete next[key];
        return next;
      });
      try {
        const result = await requests.explore(
          name,
          selectedMode,
          !!options.refresh,
          (event) => {
            if (!requests.isCurrent(ticket)) return;
            if (event.type === "status")
              setLoadingStage(
                event.stage === "search"
                  ? "正在检索论文…"
                  : "正在检查缓存或等待已有分析…",
              );
            if (event.type === "partial") {
              displayed.current = event.field;
              setField(event.field);
              setLoadingStage(
                event.stage === "papers"
                  ? "论文已找到，正在分析领域关系和阅读价值…"
                  : "地图已生成，正在完成论文评价…",
              );
            }
          },
        );
        setHistory((old) =>
          old.some((h) => keyOf(h.name) === keyOf(result.name))
            ? old
            : [...old, { name: result.name, parent }].slice(-50),
        );
        if (selectedMode === modeRef.current)
          setExplored((old) => ({ ...old, [keyOf(result.name)]: result }));
        if (!requests.isCurrent(ticket)) return;
        setTrail((old) => {
          if (options.resetPath) return [result.name];
          const index = old.findIndex((n) => keyOf(n) === keyOf(result.name));
          return index >= 0 ? old.slice(0, index + 1) : [...old, result.name];
        });
        currentRef.current = result;
        displayed.current = result;
        completedMode.current = selectedMode;
        setField(result);
        setQuery(result.name);
      } catch (e) {
        if (!requests.isCurrent(ticket)) {
          if (!(e instanceof Error && e.name === "AbortError"))
            setBackgroundErrors((old) => ({
              ...old,
              [key]: {
                name,
                mode: selectedMode,
                error: e instanceof Error ? e.message : "分析失败",
              },
            }));
          return;
        }
        setField(previous);
        displayed.current = previous;
        if (previous) {
          modeRef.current = previousMode;
          setMode(previousMode);
          if (previousMode !== selectedMode)
            setExplored({ [keyOf(previous.name)]: previous });
        }
        if (e instanceof Error && e.name === "AbortError") {
          if (!previous) setField(null);
          return;
        }
        setError(
          e instanceof Error
            ? e.name === "TimeoutError"
              ? "请求超时。请检查后端和 API 配置后重试。"
              : e.message === "Failed to fetch"
                ? "无法连接后端，请确认服务已启动。"
                : e.message
            : "探索失败，请重试。",
        );
      } finally {
        if (!requests.hasPending(key))
          setPending((old) => {
            const next = { ...old };
            delete next[key];
            return next;
          });
        if (requests.isCurrent(ticket)) setBusy(false);
      }
    },
    [requests],
  );
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => {});
    void explore(initial.current, { resetPath: true, mode: initial.mode });
  }, [explore, initial.current, initial.mode]);
  useEffect(() => {
    if (field?.phase === "complete") {
      try {
        localStorage.setItem(
          "field-navigator-session-v1",
          JSON.stringify({ history, current: field.name, mode }),
        );
      } catch {
        /* nonessential */
      }
    }
  }, [history, field, mode]);
  useEffect(() => {
    if (!showHelp) return;
    const listener = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowHelp(false);
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [showHelp]);
  function changeMode(next: Mode) {
    void explore(field?.name || query || ROOT, { mode: next, resetPath: true });
  }
  const exploreNode = useCallback(
    (name: string) => {
      void explore(name);
    },
    [explore],
  );
  function exportMap() {
    setExportContent(
      JSON.stringify(
        {
          exported_at: new Date().toISOString(),
          current_field: field?.id,
          fields: Object.values(explored).map((item) => ({
            ...item,
            evidence_papers: item.evidence_papers ?? [],
          })),
        },
        null,
        2,
      ),
    );
  }
  const visibleRelations = field?.[relationTab] ?? [];
  return (
    <div className="app-shell">
      <header className="app-header">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            void explore(ROOT, { resetPath: true });
          }}
        >
          <span className="brand-symbol">
            <Compass size={23} strokeWidth={1.8} />
          </span>
          <span>
            Field Navigator<small>找到一个领域的入口</small>
          </span>
        </a>
        <SearchBar
          query={query}
          setQuery={setQuery}
          mode={mode}
          setMode={changeMode}
          busy={false}
          onSearch={() => void explore(query, { resetPath: true })}
        />
        <div className="header-actions">
          <button
            className="theme-toggle"
            aria-label={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
            title={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
            onClick={() =>
              setTheme((value) => (value === "dark" ? "light" : "dark"))
            }
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            className="help-button"
            aria-label="使用指南"
            onClick={() => setShowHelp(true)}
          >
            <Info size={17} />
            <span>使用指南</span>
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="workspace-label">
            <span className="small-symbol">
              <Layers size={15} />
            </span>
            <span>
              我的研究地图<small>LOCAL WORKSPACE</small>
            </span>
            <span className="version">MVP</span>
          </div>
          <button
            className="new-exploration"
            onClick={() => {
              setQuery("");
              document
                .querySelector<HTMLInputElement>('[aria-label="搜索科研领域"]')
                ?.focus();
            }}
          >
            <Plus size={16} />
            探索一个新领域
          </button>
          <div className="sidebar-section-label">
            <span>
              <History size={13} />
              探索记录
            </span>
            <b>{history.length}</b>
          </div>
          <nav className="history-list" aria-label="探索记录">
            {history.length ? (
              history.map((entry, index) => (
                <button
                  key={entry.name}
                  className={`history-item ${field?.name === entry.name ? "selected" : ""}`}
                  onClick={() => void explore(entry.name, { resetPath: true })}
                >
                  <span className="history-marker">
                    {entry.parent ? (
                      <GitBranch size={14} />
                    ) : (
                      <Compass size={15} />
                    )}
                  </span>
                  <span>
                    {entry.name}
                    <small>
                      {index === 0
                        ? "探索起点"
                        : explored[keyOf(entry.name)]
                          ? "已分析 · 点击返回"
                          : "已保存的探索记录"}
                    </small>
                  </span>
                  {field?.name === entry.name && (
                    <span className="active-dot" />
                  )}
                </button>
              ))
            ) : (
              <p className="sidebar-empty">搜索一个领域，开始你的探索。</p>
            )}
          </nav>
          {(Object.keys(pending).length > 0 ||
            Object.keys(backgroundErrors).length > 0) && (
            <nav className="pending-list" aria-label="后台分析">
              <div className="sidebar-section-label">后台分析</div>
              {Object.entries(pending).map(([key, job]) => (
                <button
                  className="history-item"
                  key={key}
                  onClick={() => void explore(job.name, { mode: job.mode })}
                >
                  <LoaderCircle className="spin" size={14} />
                  <span>
                    {job.name}
                    <small>分析中 · 点击查看进度</small>
                  </span>
                </button>
              ))}
              {Object.entries(backgroundErrors).map(([key, job]) => (
                <button
                  className="history-item"
                  key={key}
                  title={job.error}
                  onClick={() => void explore(job.name, { mode: job.mode })}
                >
                  <Info size={14} />
                  <span>
                    {job.name}
                    <small>分析失败 · 点击重试</small>
                  </span>
                </button>
              ))}
            </nav>
          )}
          <div className="sidebar-controls">
            <div className="sidebar-section-label">
              <span>
                <Settings2 size={14} />
                图谱显示
              </span>
            </div>
            <label className="check-row">
              <input
                type="checkbox"
                checked={showPrerequisites}
                onChange={(e) => setShowPrerequisites(e.target.checked)}
              />
              <span className="legend-dot teal" />
              前置领域
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={showSubfields}
                onChange={(e) => setShowSubfields(e.target.checked)}
              />
              <span className="legend-dot violet" />
              研究分支
            </label>
            <label className="control-label" htmlFor="depth">
              展开层数 <span>{depth} 层</span>
            </label>
            <input
              id="depth"
              type="range"
              min="1"
              max="2"
              step="1"
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            />
            <label className="control-label" htmlFor="confidence">
              最低置信度 <span>{Math.round(minConfidence * 100)}%</span>
            </label>
            <input
              id="confidence"
              type="range"
              min="0"
              max="1"
              step=".05"
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
            />
            <p className="control-hint">
              二层视图展示已探索的分支。置信度是分析判断，不是统计概率。
            </p>
          </div>
          <div className="sidebar-tip">
            <span>
              <FlaskConical size={15} />
              从一个好问题开始
            </span>
            <p>先看领域脉络，再选一篇核心论文。每个节点都是新的入口。</p>
          </div>
          <div className="local-status">
            <span className="status-dot" />
            本地工作空间
            <Database size={12} />
          </div>
        </aside>
        <section className="main-workspace">
          <div className="breadcrumb-bar">
            <div className="breadcrumbs">
              <button
                className="icon-button"
                aria-label="返回上一个领域"
                disabled={trail.length < 2}
                onClick={() => void explore(trail[trail.length - 2])}
              >
                <ArrowLeft size={16} />
              </button>
              <span>领域探索</span>
              {trail.slice(-2).map((n) => (
                <span className="breadcrumb-item" key={n}>
                  <ChevronRight size={13} />
                  <button onClick={() => void explore(n)}>{n}</button>
                </span>
              ))}
            </div>
            <button
              className="text-button"
              disabled={!field || field.phase !== "complete"}
              onClick={exportMap}
            >
              <Download size={14} />
              <span>导出地图</span>
            </button>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <Info size={17} />
              <span>{error}</span>
              <button
                disabled={busy}
                onClick={() =>
                  void explore(loadingName || query || ROOT, {
                    refresh: failedRefresh.current,
                    mode: failedMode.current,
                  })
                }
              >
                重试
              </button>
              <button aria-label="关闭错误提示" onClick={() => setError("")}>
                <X size={14} />
              </button>
            </div>
          )}
          {field ? (
            <>
              <section className="field-heading">
                <div className="heading-eyebrow">
                  <span>
                    <span className="status-dot" />
                    FIELD EXPLORER
                  </span>
                  <span className="source-badge">
                    {field.paper_source === "demo" ? "离线演示" : "OpenAlex"} ·{" "}
                    {field.analysis_source === "pending"
                      ? "论文初筛"
                      : field.analysis_source === "mock"
                        ? "预设拆分"
                        : "LLM 分析"}
                  </span>
                </div>
                <h1>{field.name}</h1>
                <p>{field.summary}</p>
                <div className="field-stats">
                  <span>
                    <BookOpen size={13} />
                    {field.core_papers.length} 篇
                    {field.phase === "complete" ? "核心论文" : "初筛论文"}
                  </span>
                  <span>
                    <GitBranch size={13} />
                    {field.subfields.length} 个研究分支
                  </span>
                  <span>
                    <Layers size={13} />
                    {field.prerequisites.length} 个前置领域
                  </span>
                  <span className="cache-status">
                    <Check size={13} />
                    {field.phase !== "complete"
                      ? "分析中 · 尚未保存"
                      : field.cache_hit
                        ? "已读取缓存"
                        : "分析已保存"}
                  </span>
                  <button
                    className="refresh-button"
                    disabled={!!pending[requestKey(field.name, mode)]}
                    onClick={() => void explore(field.name, { refresh: true })}
                  >
                    <RotateCw size={13} />
                    重新分析
                  </button>
                </div>
              </section>
              <div className="content-columns">
                <div className="map-column">
                  <section className="relation-table">
                    <div className="relation-table-top">
                      <div className="relation-tabs">
                        <button
                          className={
                            relationTab === "subfields" ? "active" : ""
                          }
                          onClick={() => {
                            setRelationTab("subfields");
                            setShowTable(true);
                          }}
                        >
                          研究分支 <b>{field.subfields.length}</b>
                        </button>
                        <button
                          className={
                            relationTab === "prerequisites" ? "active" : ""
                          }
                          onClick={() => {
                            setRelationTab("prerequisites");
                            setShowTable(true);
                          }}
                        >
                          前置领域 <b>{field.prerequisites.length}</b>
                        </button>
                      </div>
                      <button
                        className="text-button table-toggle"
                        aria-expanded={showTable}
                        onClick={() => setShowTable((v) => !v)}
                      >
                        {showTable ? "收起列表" : "展开列表"}
                        <ArrowRight size={13} />
                      </button>
                    </div>
                    {showTable && (
                      <>
                        <div className="table-head">
                          <span>FIELD / 领域</span>
                          <span>
                            {field.analysis_source === "mock"
                              ? "演示置信度"
                              : "模型置信度"}
                          </span>
                          <span>状态</span>
                        </div>
                        <div className="table-body">
                          {visibleRelations.length ? (
                            visibleRelations.map((r) => (
                              <button
                                className="table-row"
                                key={r.name}
                                onClick={() => exploreNode(r.name)}
                                title={r.reason}
                              >
                                <span>
                                  <i
                                    className={`legend-dot ${relationTab === "prerequisites" ? "teal" : "violet"}`}
                                  />
                                  {r.name}
                                </span>
                                <span>
                                  <i className="confidence-bar">
                                    <i
                                      style={{
                                        width: `${r.confidence * 100}%`,
                                      }}
                                    />
                                  </i>
                                  {Math.round(r.confidence * 100)}%
                                </span>
                                <span>
                                  {explored[keyOf(r.name)] ? (
                                    <>
                                      <Check size={12} />
                                      已探索
                                    </>
                                  ) : (
                                    <>
                                      探索
                                      <ArrowUpRight size={13} />
                                    </>
                                  )}
                                </span>
                              </button>
                            ))
                          ) : (
                            <div className="empty-relations">
                              当前未提供更多
                              {relationTab === "subfields"
                                ? "分支"
                                : "前置领域"}
                              。可阅读右侧论文或搜索新的领域。
                            </div>
                          )}
                        </div>
                      </>
                    )}
                  </section>
                  <section className="graph-section">
                    <FieldGraph
                      theme={theme}
                      field={field}
                      explored={explored}
                      onExplore={exploreNode}
                      showPrerequisites={showPrerequisites}
                      showSubfields={showSubfields}
                      minConfidence={minConfidence}
                      depth={depth}
                      busy={false}
                    />
                  </section>
                </div>
                <DetailPanel
                  field={field}
                  onExplore={exploreNode}
                  busy={false}
                />
              </div>
              <div className="workspace-footer">
                <span>
                  <Info size={12} />
                  {field.paper_source === "demo"
                    ? "演示模式：预设领域关系与阅读优先级；书目已核对，未提供实时引用量。"
                    : field.analysis_source === "mock"
                      ? "实时论文 + 预设拆分；配置 LLM 后可分析任意领域。"
                      : "论文来自 OpenAlex；领域关系是模型推断，请结合原文判断。"}
                </span>
                <span>
                  {field.candidate_count} 篇候选论文
                  {field.analyzed_paper_count != null &&
                  field.analyzed_paper_count < field.candidate_count
                    ? ` · ${field.analyzed_paper_count} 篇参与分析`
                    : ""}
                </span>
              </div>
            </>
          ) : (
            <div className="welcome">
              <div className="welcome-icon">
                <Network size={42} strokeWidth={1} />
              </div>
              <span className="eyebrow">A MAP FOR YOUR NEXT QUESTION</span>
              <h1>先看见领域，再深入其中。</h1>
              <p>
                找到知识的主干、分支和前置领域，
                <br />
                让第一篇论文有一个清晰的起点。
              </p>
              <button
                className="primary"
                onClick={() => {
                  modeRef.current = "demo";
                  setMode("demo");
                  void explore(ROOT, { mode: "demo", resetPath: true });
                }}
              >
                <Compass size={17} />
                体验 NHSE 示例
                <ArrowUpRight size={16} />
              </button>
            </div>
          )}
          {busy && (
            <div className="loading-toast" role="status">
              <LoaderCircle className="spin" size={19} />
              <div>
                <strong>正在探索 {loadingName}</strong>
                <span>{loadingStage}</span>
              </div>
              <button
                className="text-button"
                onClick={() => requests.cancel(activeRequest.current)}
              >
                取消
              </button>
            </div>
          )}
        </section>
      </div>
      {exportContent && (
        <div
          className="modal-backdrop"
          onClick={() => setExportContent("")}
          onKeyDown={(e) => {
            if (e.key === "Escape") setExportContent("");
          }}
        >
          <section
            className="help-modal export-modal"
            role="dialog"
            aria-modal="true"
            aria-label="导出研究地图"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              autoFocus
              className="close-modal icon-button"
              aria-label="关闭导出"
              onClick={() => setExportContent("")}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">YOUR RESEARCH MAP</span>
            <h2>导出研究地图</h2>
            <p>保存本次已加载的领域、关系、论文及选择理由。</p>
            <textarea
              aria-label="地图 JSON"
              readOnly
              value={exportContent}
              onFocus={(e) => e.currentTarget.select()}
            />
            <a
              className="download-json"
              href={exportUrl}
              download="field-navigator-map.json"
            >
              <Download size={16} />
              下载 JSON
            </a>
            <p className="export-hint">
              也可选中上方内容复制，在其他工具中继续使用。
            </p>
          </section>
        </div>
      )}
      {showHelp && (
        <div className="modal-backdrop" onClick={() => setShowHelp(false)}>
          <section
            className="help-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              autoFocus
              className="close-modal icon-button"
              aria-label="关闭使用指南"
              onClick={() => setShowHelp(false)}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">GETTING STARTED</span>
            <h2 id="help-title">从一个领域开始</h2>
            <ol>
              <li>
                <strong>搜索你想了解的领域</strong>
                <p>
                  建议使用英文领域名称，也支持 NHSE 和「非厄米趋肤效应」别名。
                </p>
              </li>
              <li>
                <strong>从主干走向分支</strong>
                <p>
                  前置领域在左，研究分支在右。点击节点深入，左侧记录随时带你返回。
                </p>
              </li>
              <li>
                <strong>带着理由选择论文</strong>
                <p>
                  展开「为什么读这篇」查看理由与评分。标题链接到 DOI
                  或原文页面。
                </p>
              </li>
            </ol>
            <div className="help-modes">
              <h3>数据模式与配置</h3>
              <p>
                <b>自动：</b>尝试 OpenAlex，失败时仅对预设 NHSE
                领域使用演示资料。
                <br />
                <b>实时：</b>只用 OpenAlex，失败会直接提示。
                <br />
                <b>离线演示：</b>无需
                key；领域关系、置信度和阅读优先级为预设示例。
              </p>
              <p>
                在项目根目录的 <code>.env</code> 配置{" "}
                <code>OPENALEX_API_KEY</code> 和{" "}
                <code>LLM_API_KEY / LLM_MODEL</code> 后重启后端。
              </p>
              <div className="config-status">
                <span>
                  OpenAlex key：
                  {health?.openalex_key_configured ? "已配置" : "未配置"}
                </span>
                <span>
                  LLM：
                  {(health?.llm_ready ?? health?.llm_configured)
                    ? "已配置"
                    : "预设演示"}
                </span>
              </div>
            </div>
            <button className="primary" onClick={() => setShowHelp(false)}>
              开始探索
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
