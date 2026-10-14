import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Bookmark,
  Check,
  ChevronRight,
  Compass,
  Copy,
  Database,
  Download,
  FileText,
  GitBranch,
  History,
  Info,
  Layers,
  List,
  LoaderCircle,
  Moon,
  Plus,
  RotateCw,
  ShieldCheck,
  Sun,
  Trash2,
  X,
  Network,
} from "lucide-react";
import { exploreField, resolveQuery } from "./api/client";
import {
  ExplorationRequests,
  nextTrailState,
  requestKey,
  normalizeField as keyOf,
  normalizeResearchQuestion,
  type TrailContexts,
} from "./state/exploration";
import {
  loadSession,
  saveSession,
  clearSession,
  type HistoryEntry,
} from "./state/session";
import { buildResearchBrief, serializeMap } from "./state/export";
import {
  addToLibrary,
  loadLibrary,
  saveLibrary,
  updateLibraryItem,
  removeLibraryItem,
  exportLibraryMarkdown,
  getSavedPaperIds,
  isSavedPaper,
  MAX_LIBRARY_ITEMS,
  type SavedPaper,
} from "./state/library";
import { DetailPanel } from "./components/DetailPanel";
import { SearchBar } from "./components/SearchBar";
import { ResearchStart } from "./components/ResearchStart";
import { DirectionChooser } from "./components/DirectionChooser";
import { RelationEvidenceList } from "./components/RelationEvidenceList";
import { ResearchLibrary } from "./components/ResearchLibrary";
import type {
  CorePaper,
  FieldNode,
  Mode,
  QueryCandidate,
  QueryResolution,
} from "./types";

const ROOT = "Non-Hermitian Skin Effect";
const FieldGraph = lazy(() =>
  import("./components/FieldGraph").then((module) => ({
    default: module.FieldGraph,
  })),
);
type View = "home" | "map" | "library";
type ExportDocument = {
  title: string;
  content: string;
  filename: string;
  format: "markdown" | "json";
};
type PendingJob = {
  name: string;
  mode: Mode;
  researchQuestion?: string;
};
function nodesForMode(
  snapshots: Record<string, FieldNode>,
  mode: Mode,
  researchQuestion?: string | null,
) {
  const question = normalizeResearchQuestion(researchQuestion);
  const result: Record<string, FieldNode> = {};
  for (const [key, node] of Object.entries(snapshots)) {
    if (!key.startsWith(`${mode}:`)) continue;
    const nodeQuestion = normalizeResearchQuestion(node.research_question);
    // Contextual root fields are isolated. Context-free child explorations
    // remain visible from any root because children deliberately do not inherit
    // the parent's original question.
    if (question && nodeQuestion && nodeQuestion !== question) continue;
    if (!question && nodeQuestion) continue;
    result[keyOf(node.name)] = node;
  }
  return result;
}
function shortQuestion(value?: string | null) {
  const text = normalizeResearchQuestion(value);
  if (!text) return "";
  return text.length > 280 ? `${text.slice(0, 280)}…` : text;
}
function shortDate(value?: string) {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
function sourceLabel(field: FieldNode) {
  if (field.paper_source === "demo") return "离线示例 · 真实书目 / 预设关系";
  if (field.phase !== "complete") return "真实论文 · 分析未完成";
  if (field.analysis_source === "mock") return "真实论文 · 未使用模型分析";
  return "OpenAlex 论文 · AI 分析";
}
function friendlyError(error: unknown) {
  if (!(error instanceof Error)) return "暂时无法完成探索，请重试。";
  if (error.name === "TimeoutError")
    return "这次分析等待较久，已停止等待。已完成的检索阶段可以在重试时复用。";
  if (error.message === "Failed to fetch")
    return "暂时无法连接研究服务。可以先体验离线示例，或稍后重试。";
  return error.message;
}

export default function App() {
  const [initial] = useState(loadSession);
  const restored =
    initial.snapshots[
      requestKey(
        initial.current,
        initial.mode,
        initial.current_research_question,
      )
    ] ?? null;
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  const [view, setView] = useState<View>(restored ? "map" : "home");
  const [query, setQuery] = useState(restored ? initial.current : "");
  const [mode, setMode] = useState<Mode>(initial.mode);
  const modeRef = useRef(mode);
  const [field, setField] = useState<FieldNode | null>(restored);
  const currentRef = useRef<FieldNode | null>(restored);
  const displayed = useRef<FieldNode | null>(restored);
  const completedMode = useRef<Mode>(initial.mode);
  const [history, setHistory] = useState<HistoryEntry[]>(initial.history);
  const [snapshots, setSnapshots] = useState<Record<string, FieldNode>>(
    initial.snapshots,
  );
  const snapshotsRef = useRef(snapshots);
  snapshotsRef.current = snapshots;
  const [trail, setTrail] = useState<string[]>(restored ? initial.trail : []);
  const trailRef = useRef(trail);
  trailRef.current = trail;
  const initialTrailContexts: TrailContexts =
    restored && initial.trail.length
      ? {
          ...(initial.trail_contexts ?? {}),
          ...(initial.current_research_question
            ? { "0": initial.current_research_question }
            : {}),
        }
      : {};
  const [trailContexts, setTrailContexts] =
    useState<TrailContexts>(initialTrailContexts);
  const trailContextsRef = useRef<TrailContexts>(trailContexts);
  trailContextsRef.current = trailContexts;
  const [explored, setExplored] = useState<Record<string, FieldNode>>(() =>
    nodesForMode(
      initial.snapshots,
      initial.mode,
      initial.current_research_question,
    ),
  );
  const [requests] = useState(() => new ExplorationRequests(exploreField));
  const activeRequest = useRef("");
  const historyGeneration = useRef(0);
  const failedOperation = useRef<"resolve" | "explore">("resolve");
  const failedMode = useRef<Mode>(initial.mode);
  const failedRefresh = useRef(false);
  const failedResearchQuestion = useRef<string | undefined>(
    initial.current_research_question,
  );
  const [pending, setPending] = useState<Record<string, PendingJob>>({});
  const [backgroundErrors, setBackgroundErrors] = useState<
    Record<string, PendingJob & { error: string }>
  >({});
  const [busy, setBusy] = useState(false);
  const [loadingName, setLoadingName] = useState("");
  const [loadingStage, setLoadingStage] = useState("准备研究工作空间…");
  const [startedAt, setStartedAt] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [storageWarning, setStorageWarning] = useState("");
  const [toast, setToast] = useState("");
  const [resolution, setResolution] = useState<QueryResolution | null>(null);
  const [resolving, setResolving] = useState(false);
  const resolutionController = useRef<AbortController | null>(null);
  const resolutionTicket = useRef(0);
  const [chosenDirection, setChosenDirection] = useState<QueryCandidate | null>(
    null,
  );
  const [showHelp, setShowHelp] = useState(false);
  const dialogReturnFocus = useRef<HTMLElement | null>(null);
  const [showPrerequisites, setShowPrerequisites] = useState(true);
  const [showSubfields, setShowSubfields] = useState(true);
  const [depth, setDepth] = useState(1);
  const [maxRelations, setMaxRelations] = useState(3);
  const [minConfidence, setMinConfidence] = useState(0);
  const [relationTab, setRelationTab] = useState<"subfields" | "prerequisites">(
    "subfields",
  );
  const [mapPresentation, setMapPresentation] = useState<"graph" | "list">(
    () => (window.innerWidth < 1100 ? "list" : "graph"),
  );
  const [health, setHealth] = useState<{
    llm_ready?: boolean;
    llm_configured?: boolean;
    openalex_key_configured?: boolean;
  } | null>(null);
  const [library, setLibrary] = useState<SavedPaper[]>(loadLibrary);
  const [libraryWarning, setLibraryWarning] = useState("");
  const lastLibrary = useRef<SavedPaper[] | null>(null);
  const [exportDocument, setExportDocument] = useState<ExportDocument | null>(
    null,
  );
  const [exportCopied, setExportCopied] = useState(false);
  const exportUrl = useMemo(
    () =>
      exportDocument
        ? URL.createObjectURL(
            new Blob([exportDocument.content], {
              type:
                exportDocument.format === "json"
                  ? "application/json;charset=utf-8"
                  : "text/markdown;charset=utf-8",
            }),
          )
        : "",
    [exportDocument],
  );
  useEffect(
    () => () => {
      if (exportUrl) URL.revokeObjectURL(exportUrl);
    },
    [exportUrl],
  );
  useEffect(
    () => () => {
      requests.dispose();
      resolutionController.current?.abort();
    },
    [requests],
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#111923" : "#f7f8fa");
    try {
      localStorage.setItem("field-navigator-theme", theme);
    } catch {
      /* Appearance remains usable without persistence. */
    }
  }, [theme]);
  useEffect(() => {
    // Restoring research never starts an external paper/model request.
    const controller = new AbortController();
    void fetch("/api/health", { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then(setHealth)
      .catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const complete =
      field?.phase === "complete" && completedMode.current === mode;
    const ok = saveSession({
      history,
      current: complete ? field.name : "",
      current_research_question: complete
        ? normalizeResearchQuestion(field.research_question) || undefined
        : undefined,
      mode,
      snapshots,
      trail,
      trail_contexts: trailContexts,
    });
    setStorageWarning(
      ok
        ? ""
        : "浏览器未能保存研究记录；当前页面仍可使用，请导出简报保留结果。",
    );
  }, [history, field, mode, snapshots, trail, trailContexts]);
  useEffect(() => {
    setLibraryWarning(
      saveLibrary(library)
        ? ""
        : "阅读清单暂未写入浏览器存储。请导出清单保留笔记，避免关闭页面后丢失。",
    );
  }, [library]);
  useEffect(() => {
    if (!busy && !resolving) return;
    const update = () =>
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [busy, resolving, startedAt]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4200);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!showHelp && !exportDocument) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowHelp(false);
        setExportDocument(null);
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
      const elements = dialog
        ? Array.from(
            dialog.querySelectorAll<HTMLElement>(
              'button:not(:disabled), a[href], textarea, input, select, [tabindex="0"]',
            ),
          )
        : [];
      const first = elements[0],
        last = elements[elements.length - 1];
      if (!first || !last) return;
      if (
        !dialog?.contains(document.activeElement) ||
        (event.shiftKey && document.activeElement === first) ||
        (!event.shiftKey && document.activeElement === last)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      document.body.style.overflow = previousOverflow;
      if (dialogReturnFocus.current?.isConnected)
        dialogReturnFocus.current.focus();
    };
  }, [showHelp, exportDocument]);

  function updateTrail(
    resultName: string,
    researchQuestion?: string | null,
    resetPath = false,
  ) {
    const next = nextTrailState(
      trailRef.current,
      trailContextsRef.current,
      resultName,
      researchQuestion,
      resetPath,
    );
    const nextTrail = next.trail;
    const nextContexts = next.contexts;
    trailRef.current = nextTrail;
    trailContextsRef.current = nextContexts;
    setTrail(nextTrail);
    setTrailContexts(nextContexts);
  }

  const explore = useCallback(
    async (
      name: string,
      options: {
        refresh?: boolean;
        resetPath?: boolean;
        mode?: Mode;
        researchQuestion?: string | null;
      } = {},
    ) => {
      const selectedMode = options.mode ?? modeRef.current;
      const ticket = requests.select();
      const generation = historyGeneration.current;
      failedOperation.current = "explore";
      const explicitQuestion =
        options.researchQuestion !== undefined
          ? normalizeResearchQuestion(options.researchQuestion) || undefined
          : undefined;
      const hasExplicitQuestion = options.researchQuestion !== undefined;
      const sameCurrentField =
        currentRef.current &&
        keyOf(currentRef.current.name) === keyOf(name) &&
        completedMode.current === selectedMode;
      const researchQuestion = hasExplicitQuestion
        ? explicitQuestion
        : sameCurrentField
          ? normalizeResearchQuestion(currentRef.current?.research_question) ||
            undefined
          : undefined;
      const key = requestKey(name, selectedMode, researchQuestion);
      activeRequest.current = key;
      modeRef.current = selectedMode;
      setMode(selectedMode);
      setExplored(
        nodesForMode(snapshotsRef.current, selectedMode, researchQuestion),
      );
      failedMode.current = selectedMode;
      failedRefresh.current = !!options.refresh;
      failedResearchQuestion.current = researchQuestion;
      setResolution(null);
      setView("map");
      setError("");
      const previous = currentRef.current;
      const previousMode = completedMode.current;
      const previousTrail = trailRef.current;
      const previousTrailContexts = trailContextsRef.current;
      const newScope =
        !!options.resetPath &&
        (!previous ||
          requestKey(
            previous.name,
            previousMode,
            previous.research_question,
          ) !== key);
      const parent = options.resetPath
        ? null
        : (displayed.current?.name ?? null);
      const saved = snapshotsRef.current[key];
      if (saved && saved.phase === "complete" && !options.refresh) {
        const result = { ...saved, cache_hit: true };
        currentRef.current = displayed.current = result;
        completedMode.current = selectedMode;
        setField(result);
        setQuery(result.name);
        setBusy(false);
        updateTrail(
          result.name,
          result.research_question ?? researchQuestion,
          !!options.resetPath,
        );
        return;
      }
      if (newScope) {
        displayed.current = null;
        setField(null);
        updateTrail(name, researchQuestion, true);
        setQuery(name);
      }
      setBusy(true);
      setStartedAt(Date.now());
      setLoadingName(name);
      setLoadingStage("检查已保存的分析阶段…");
      setPending((old) => ({
        ...old,
        [key]: { name, mode: selectedMode, researchQuestion },
      }));
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
                  ? "检索真实论文与摘要…"
                  : "检查缓存，或等待已有分析…",
              );
            if (event.type === "partial") {
              displayed.current = event.field;
              setField(event.field);
              setLoadingStage(
                event.stage === "papers"
                  ? "论文已找到，正在梳理研究方向…"
                  : "地图已完成，正在整理阅读建议…",
              );
            }
          },
          researchQuestion,
        );
        if (generation !== historyGeneration.current) return;
        if (result.phase === "complete") {
          setSnapshots((old) => ({
            ...old,
            [requestKey(result.name, selectedMode, researchQuestion)]: result,
          }));
          setHistory((old) =>
            [
              ...old.filter(
                (entry) =>
                  requestKey(
                    entry.name,
                    entry.mode,
                    entry.research_question,
                  ) !== requestKey(result.name, selectedMode, researchQuestion),
              ),
              {
                name: result.name,
                parent,
                mode: selectedMode,
                ...(normalizeResearchQuestion(result.research_question)
                  ? {
                      research_question: normalizeResearchQuestion(
                        result.research_question,
                      ),
                    }
                  : {}),
                created_at: result.created_at,
                paper_source: result.paper_source,
                analysis_source: result.analysis_source,
              },
            ].slice(-50),
          );
        }
        if (!requests.isCurrent(ticket)) return;
        // Only the request that still owns the selected view may enrich the
        // two-level graph. A stale goal can still be useful in snapshots and
        // history above, but must never replace the current goal's child map.
        if (selectedMode === modeRef.current)
          setExplored((old) => ({ ...old, [keyOf(result.name)]: result }));
        updateTrail(
          result.name,
          result.research_question ?? researchQuestion,
          !!options.resetPath,
        );
        currentRef.current = displayed.current = result;
        completedMode.current = selectedMode;
        setField(result);
        setQuery(result.name);
      } catch (cause) {
        if (generation !== historyGeneration.current) return;
        if (!requests.isCurrent(ticket)) {
          if (!(cause instanceof Error && cause.name === "AbortError"))
            setBackgroundErrors((old) => ({
              ...old,
              [key]: {
                name,
                mode: selectedMode,
                researchQuestion,
                error: friendlyError(cause),
              },
            }));
          return;
        }
        setField(previous);
        displayed.current = previous;
        if (newScope) {
          setView("home");
          trailRef.current = previousTrail;
          trailContextsRef.current = previousTrailContexts;
          setTrail(previousTrail);
          setTrailContexts(previousTrailContexts);
        }
        if (previous) {
          modeRef.current = previousMode;
          setMode(previousMode);
          setExplored(
            nodesForMode(
              snapshotsRef.current,
              previousMode,
              previous.research_question,
            ),
          );
        }
        if (!(cause instanceof Error && cause.name === "AbortError"))
          setError(friendlyError(cause));
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

  function dismissResolution() {
    resolutionTicket.current++;
    resolutionController.current?.abort();
    setResolving(false);
    setResolution(null);
  }
  function goHome() {
    dismissResolution();
    requests.select();
    setBusy(false);
    setView("home");
    setError("");
  }
  function changeMode(next: Mode) {
    goHome();
    modeRef.current = next;
    setMode(next);
    setChosenDirection(null);
  }
  async function submitQuery() {
    const input = query.trim();
    failedOperation.current = "resolve";
    if (input.length < 2) {
      setError("请写下至少两个字的领域或研究问题。");
      return;
    }
    resolutionController.current?.abort();
    const controller = new AbortController();
    resolutionController.current = controller;
    const ticket = ++resolutionTicket.current;
    const selectedMode = modeRef.current;
    requests.select();
    setBusy(false);
    setResolving(true);
    setResolution(null);
    setError("");
    setStartedAt(Date.now());
    try {
      const result = await resolveQuery(input, selectedMode, controller.signal);
      if (ticket !== resolutionTicket.current || controller.signal.aborted)
        return;
      setResolving(false);
      if (result.status === "ready" && result.candidates.length === 1) {
        setChosenDirection(result.candidates[0]);
        void explore(result.candidates[0].query, {
          resetPath: true,
          mode: selectedMode,
          researchQuestion: input,
        });
      } else setResolution(result);
    } catch (cause) {
      if (
        ticket === resolutionTicket.current &&
        !(cause instanceof Error && cause.name === "AbortError")
      )
        setError(friendlyError(cause));
    } finally {
      if (ticket === resolutionTicket.current) setResolving(false);
    }
  }
  function chooseDirection(candidate: QueryCandidate) {
    const researchQuestion =
      normalizeResearchQuestion(resolution?.query) ||
      normalizeResearchQuestion(query) ||
      undefined;
    setChosenDirection(candidate);
    void explore(candidate.query, { resetPath: true, researchQuestion });
  }
  function exploreNode(name: string, pathIndex?: number) {
    dismissResolution();
    setChosenDirection(null);
    const trailNames = trailRef.current.map((item) => keyOf(item));
    const contextIndex = pathIndex ?? [...trailNames].lastIndexOf(keyOf(name));
    void explore(name, {
      researchQuestion:
        contextIndex >= 0
          ? (trailContextsRef.current[String(contextIndex)] ?? null)
          : null,
    });
  }
  function openLibrary() {
    dismissResolution();
    requests.select();
    setBusy(false);
    setView("library");
    setError("");
  }
  function closeLibrary() {
    const current = currentRef.current;
    if (!current) {
      goHome();
      return;
    }
    modeRef.current = completedMode.current;
    setMode(completedMode.current);
    setField(current);
    displayed.current = current;
    setExplored(
      nodesForMode(
        snapshotsRef.current,
        completedMode.current,
        current.research_question,
      ),
    );
    setQuery(current.name);
    setView("map");
  }
  function addPaper(core: CorePaper, fieldName: string) {
    const existing = isSavedPaper(core.paper, getSavedPaperIds(library));
    if (!existing && library.length >= MAX_LIBRARY_ITEMS) {
      setToast(
        `清单已达到 ${MAX_LIBRARY_ITEMS} 篇。请先导出或移除不需要的论文。`,
      );
      return;
    }
    setLibrary((old) => addToLibrary(old, core, fieldName));
    setToast(
      existing
        ? "已为这篇论文补充当前领域来源。"
        : "已加入当前阅读清单，可以继续阅读和记笔记。",
    );
  }
  function saveReadingStart() {
    if (!field) return;
    const selected = field.core_papers.slice(0, 3);
    const next = selected.reduce(
      (items, core) => addToLibrary(items, core, field.name),
      library,
    );
    const added = next.length - library.length;
    const skipped = selected.filter(
      (core) => !isSavedPaper(core.paper, getSavedPaperIds(next)),
    ).length;
    setLibrary(next);
    setToast(
      skipped
        ? `新增 ${added} 篇；清单已满，${skipped} 篇未加入。旧收藏和笔记均保留。`
        : added
          ? `已新增 ${added} 篇阅读起点；重复论文会合并领域来源。`
          : "这些阅读起点已在清单，已合并当前领域来源。",
    );
  }
  function clearHistory() {
    historyGeneration.current++;
    requests.select();
    requests.dispose();
    dismissResolution();
    setHistory([]);
    setSnapshots({});
    setExplored({});
    trailRef.current = [];
    trailContextsRef.current = {};
    setTrailContexts({});
    setTrail([]);
    setField(null);
    currentRef.current = displayed.current = null;
    setPending({});
    setBackgroundErrors({});
    setBusy(false);
    setView("home");
    setQuery("");
    if (!clearSession())
      setStorageWarning("浏览器未能清除旧记录，请检查浏览器的存储设置。");
    setToast("已清除本机探索记录；阅读清单保留。");
  }
  function openExport(document: ExportDocument) {
    dialogReturnFocus.current = window.document
      .activeElement as HTMLElement | null;
    setExportDocument(document);
    setExportCopied(false);
  }
  function exportBrief() {
    if (field)
      openExport({
        title: "研究入门简报",
        content: buildResearchBrief(field, Object.values(explored)),
        filename: "field-navigator-research-brief.md",
        format: "markdown",
      });
  }
  const savedPaperIds = useMemo(() => getSavedPaperIds(library), [library]);
  const previousEntry = history[history.length - 1];
  const relevantWarnings = field?.warnings ?? [];
  const countPending = Object.keys(pending).length;
  const firstPaper = field?.core_papers[0];

  return (
    <div className="app-shell">
      <header className="app-header">
        <button
          className="brand"
          onClick={goHome}
          aria-label="Field Navigator 首页"
        >
          <span className="brand-symbol">
            <Compass size={24} strokeWidth={1.7} />
          </span>
          <span>
            Field Navigator<small>让研究有方向</small>
          </span>
        </button>
        {view !== "home" && (
          <SearchBar
            query={query}
            setQuery={setQuery}
            mode={mode}
            setMode={changeMode}
            busy={resolving}
            onSearch={() => void submitQuery()}
          />
        )}
        <div className="header-actions">
          <span className="private-badge">
            <ShieldCheck size={14} /> 浏览器本地工作空间
          </span>
          <button
            className="theme-toggle icon-button"
            aria-label={theme === "light" ? "切换到暗色模式" : "切换到亮色模式"}
            onClick={() =>
              setTheme((old) => (old === "light" ? "dark" : "light"))
            }
          >
            {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <button
            className="help-button"
            aria-label="使用指南"
            onClick={() => {
              dialogReturnFocus.current =
                document.activeElement as HTMLElement | null;
              setShowHelp(true);
            }}
          >
            <Info size={17} />
            <span>使用指南</span>
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="workspace-label">
            <Layers size={16} />
            <span>
              研究工作空间<small>YOUR RESEARCH DESK</small>
            </span>
          </div>
          <button
            className={`new-exploration ${view === "home" ? "selected" : ""}`}
            onClick={() => {
              goHome();
              setQuery("");
              modeRef.current = "auto";
              setMode("auto");
              setTimeout(
                () =>
                  document
                    .querySelector<HTMLInputElement>(
                      '[aria-label="搜索科研领域"]',
                    )
                    ?.focus(),
                0,
              );
            }}
          >
            <Plus size={17} /> 新的研究问题
          </button>
          <button
            className={`library-nav ${view === "library" ? "selected" : ""}`}
            onClick={openLibrary}
          >
            <Bookmark size={17} /> 阅读清单 <b>{library.length}</b>
          </button>
          <div className="sidebar-section-label">
            <span>
              <History size={13} /> 最近探索
            </span>
            <b>{history.length}</b>
          </div>
          <nav className="history-list" aria-label="探索记录">
            {history.length ? (
              [...history].reverse().map((entry) => (
                <button
                  key={requestKey(
                    entry.name,
                    entry.mode,
                    entry.research_question,
                  )}
                  title={entry.research_question || entry.name}
                  className={`history-item ${view === "map" && field && requestKey(field.name, completedMode.current, field.research_question) === requestKey(entry.name, entry.mode, entry.research_question) ? "selected" : ""}`}
                  onClick={() => {
                    dismissResolution();
                    setChosenDirection(null);
                    void explore(entry.name, {
                      resetPath: true,
                      mode: entry.mode,
                      researchQuestion: entry.research_question ?? null,
                    });
                  }}
                >
                  <span className="history-marker">
                    {entry.parent ? (
                      <GitBranch size={15} />
                    ) : (
                      <Compass size={15} />
                    )}
                  </span>
                  <span>
                    {entry.name}
                    <small>
                      {entry.paper_source === "demo" || entry.mode === "demo"
                        ? "离线示例"
                        : "论文检索"}
                      {entry.created_at
                        ? ` · ${shortDate(entry.created_at)}`
                        : " · 点击恢复"}
                    </small>
                  </span>
                </button>
              ))
            ) : (
              <div className="sidebar-empty">
                <Compass size={23} />
                <p>
                  每一次探索，
                  <br />
                  都会在这里留下起点。
                </p>
              </div>
            )}
          </nav>
          {(countPending > 0 || Object.keys(backgroundErrors).length > 0) && (
            <nav className="pending-list" aria-label="后台分析">
              <div className="sidebar-section-label">
                后台分析 <b>{countPending}</b>
              </div>
              {Object.entries(pending).map(([key, job]) => (
                <div className="pending-job" key={key}>
                  <button
                    onClick={() =>
                      void explore(job.name, {
                        mode: job.mode,
                        researchQuestion: job.researchQuestion ?? null,
                      })
                    }
                  >
                    <LoaderCircle size={14} className="spin" />
                    <span>
                      {job.name}
                      <small>点击查看进度</small>
                    </span>
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`取消分析 ${job.name}`}
                    onClick={() => requests.cancel(key)}
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
              {Object.entries(backgroundErrors).map(([key, job]) => (
                <button
                  className="history-item failed"
                  key={key}
                  title={job.error}
                  onClick={() =>
                    void explore(job.name, {
                      mode: job.mode,
                      researchQuestion: job.researchQuestion ?? null,
                    })
                  }
                >
                  <Info size={14} />
                  <span>
                    {job.name}
                    <small>失败 · 点击重试</small>
                  </span>
                </button>
              ))}
            </nav>
          )}
          <div className="sidebar-bottom">
            <div className="sidebar-tip">
              <BookOpen size={18} />
              <strong>收藏，是研究的下一步。</strong>
              <p>把有用的论文留下，再用笔记连接它们。</p>
            </div>
            <div className="local-status">
              <Database size={12} />
              <span>记录仅存于此浏览器</span>
              {history.length > 0 && (
                <button
                  className="icon-button"
                  aria-label="清除探索记录"
                  title="清除探索记录，保留阅读清单"
                  onClick={clearHistory}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          </div>
        </aside>
        <main className={`main-workspace view-${view}`}>
          {(storageWarning || libraryWarning) && (
            <div className="storage-warning" role="alert">
              <Info size={16} />
              <span>
                {[libraryWarning, storageWarning].filter(Boolean).join(" ")}
              </span>
            </div>
          )}
          {error && (
            <div className="error-banner" role="alert">
              <Info size={17} />
              <span>{error}</span>
              <button
                onClick={() => {
                  if (failedOperation.current === "explore" && loadingName)
                    void explore(loadingName, {
                      refresh: failedRefresh.current,
                      mode: failedMode.current,
                      researchQuestion: failedResearchQuestion.current ?? null,
                    });
                  else void submitQuery();
                }}
              >
                重试
              </button>
              <button
                onClick={() => {
                  dismissResolution();
                  void explore(ROOT, { mode: "demo", resetPath: true });
                }}
              >
                体验离线示例
              </button>
              <button
                className="icon-button"
                aria-label="关闭错误提示"
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {resolution && (
            <DirectionChooser
              resolution={resolution}
              onChoose={chooseDirection}
              onDismiss={dismissResolution}
            />
          )}
          {view === "home" && (
            <ResearchStart
              query={query}
              setQuery={setQuery}
              mode={mode}
              setMode={changeMode}
              resolving={resolving}
              onSearch={() => void submitQuery()}
              onDemo={() => {
                dismissResolution();
                setChosenDirection(null);
                void explore(ROOT, { mode: "demo", resetPath: true });
              }}
              previousName={previousEntry?.name}
              onContinue={
                previousEntry
                  ? () =>
                      void explore(previousEntry.name, {
                        mode: previousEntry.mode,
                        resetPath: true,
                        researchQuestion:
                          previousEntry.research_question ?? null,
                      })
                  : undefined
              }
              savedCount={library.length}
              onLibrary={openLibrary}
            />
          )}
          {view === "library" && (
            <ResearchLibrary
              items={library}
              onUpdate={(id, patch) =>
                setLibrary((old) => updateLibraryItem(old, id, patch))
              }
              onRemove={(id) => setLibrary((old) => removeLibraryItem(old, id))}
              onClear={() => {
                setLibrary((old) => {
                  lastLibrary.current = old;
                  return [];
                });
              }}
              onUndoClear={() => {
                if (lastLibrary.current) setLibrary(lastLibrary.current);
                lastLibrary.current = null;
              }}
              onExport={() =>
                openExport({
                  title: "阅读清单与笔记",
                  content: exportLibraryMarkdown(library),
                  filename: "field-navigator-reading-list.md",
                  format: "markdown",
                })
              }
              onClose={closeLibrary}
            />
          )}
          {view === "map" && (
            <>
              <div className="breadcrumb-bar">
                <nav className="breadcrumbs" aria-label="探索路径">
                  <button
                    className="icon-button"
                    aria-label="返回上一个领域"
                    disabled={trail.length < 2}
                    onClick={() =>
                      exploreNode(trail[trail.length - 2], trail.length - 2)
                    }
                  >
                    <ArrowLeft size={16} />
                  </button>
                  <button onClick={goHome}>研究起点</button>
                  {trail.slice(-2).map((name, offset) => {
                    const trailIndex =
                      trail.length - trail.slice(-2).length + offset;
                    return (
                      <span
                        className="breadcrumb-item"
                        key={`${trailIndex}:${name}`}
                      >
                        <ChevronRight size={13} />
                        <button onClick={() => exploreNode(name, trailIndex)}>
                          {name}
                        </button>
                      </span>
                    );
                  })}
                </nav>
                <div className="map-export-actions">
                  <button
                    className="export-brief-button"
                    disabled={!field}
                    onClick={exportBrief}
                  >
                    <FileText size={14} /> 导出研究简报
                  </button>
                  <button
                    className="icon-button"
                    title="导出结构化地图 JSON"
                    aria-label="导出地图 JSON"
                    disabled={!field || field.phase !== "complete"}
                    onClick={() =>
                      openExport({
                        title: "结构化研究地图",
                        content: serializeMap(
                          Object.values(explored),
                          field?.id,
                        ),
                        filename: "field-navigator-map.json",
                        format: "json",
                      })
                    }
                  >
                    <Download size={16} />
                  </button>
                </div>
              </div>
              {field ? (
                <>
                  <section className="field-heading">
                    <div className="heading-eyebrow">
                      <span>
                        <Compass size={14} /> 研究地图
                      </span>
                      <span
                        className={`source-badge ${field.paper_source === "demo" ? "demo" : ""}`}
                      >
                        {sourceLabel(field)}
                      </span>
                    </div>
                    <h1>{field.name}</h1>
                    {chosenDirection &&
                      chosenDirection.query === field.name && (
                        <p className="chosen-scope">
                          <Compass size={13} /> 已选范围：
                          {chosenDirection.summary}
                        </p>
                      )}
                    {field.research_question && (
                      <p
                        className="research-question"
                        title={field.research_question}
                      >
                        <span>原始问题</span>
                        {shortQuestion(field.research_question)}
                      </p>
                    )}
                    <p className="field-summary">{field.summary}</p>
                    <div className="field-stats">
                      <span>
                        <BookOpen size={14} /> {field.core_papers.length} 篇
                        {field.phase === "complete" ? "阅读入口" : "初筛论文"}
                      </span>
                      <span>
                        <GitBranch size={14} /> {field.subfields.length}{" "}
                        个研究分支
                      </span>
                      <span>
                        <Layers size={14} /> {field.prerequisites.length}{" "}
                        个前置领域
                      </span>
                      <span className="cache-status">
                        {field.phase === "complete" ? (
                          <Check size={13} />
                        ) : (
                          <LoaderCircle
                            size={13}
                            className={busy ? "spin" : ""}
                          />
                        )}
                        {field.phase === "complete"
                          ? `保存于 ${shortDate(field.created_at)}`
                          : busy
                            ? "分析仍在继续"
                            : "仅完成部分分析"}
                      </span>
                      <button
                        className="refresh-button"
                        disabled={
                          !!pending[
                            requestKey(
                              field.name,
                              mode,
                              field.research_question,
                            )
                          ]
                        }
                        onClick={() =>
                          void explore(field.name, {
                            refresh: field.phase === "complete",
                            researchQuestion: field.research_question ?? null,
                          })
                        }
                      >
                        <RotateCw size={13} />
                        {field.phase === "complete" ? "更新分析" : "重试分析"}
                      </button>
                    </div>
                  </section>
                  {relevantWarnings.length > 0 && (
                    <details
                      className="analysis-notice"
                      open={field.phase !== "complete" && !busy}
                    >
                      <summary>
                        <Info size={14} />
                        <span>
                          {field.phase !== "complete" && !busy
                            ? "分析暂未完成，已有论文仍可使用"
                            : field.paper_source === "demo"
                              ? "示例关系是预设的，论文出处可核对"
                              : "查看本次分析的范围与限制"}
                        </span>
                        <ChevronRight size={14} />
                      </summary>
                      <div>
                        {relevantWarnings.map((warning) => (
                          <p key={warning}>{warning}</p>
                        ))}
                      </div>
                    </details>
                  )}
                  {firstPaper && (
                    <section className="reading-next">
                      <span className="reading-next-icon">
                        <Bookmark size={20} />
                      </span>
                      <div>
                        <span className="eyebrow">把探索变成下一步</span>
                        <h2>
                          {field.phase === "complete"
                            ? "先保存一个阅读起点"
                            : "先留下已经找到的论文"}
                        </h2>
                        <p>{firstPaper.paper.title}</p>
                        <small>
                          按当前候选排序选取，阅读清单可以自由增删。
                        </small>
                      </div>
                      <button
                        className="secondary-button"
                        onClick={saveReadingStart}
                      >
                        <Plus size={15} />
                        收藏前 {Math.min(3, field.core_papers.length)} 篇
                      </button>
                    </section>
                  )}
                  <div className="content-columns">
                    <section className="map-column">
                      <div className="map-view-toolbar">
                        <div className="view-switch" aria-label="关系展示方式">
                          <button
                            className={
                              mapPresentation === "graph" ? "active" : ""
                            }
                            onClick={() => setMapPresentation("graph")}
                          >
                            <Network size={14} /> 地图
                          </button>
                          <button
                            className={
                              mapPresentation === "list" ? "active" : ""
                            }
                            onClick={() => setMapPresentation("list")}
                          >
                            <List size={14} /> 方向与证据
                          </button>
                        </div>
                        <span className="map-view-hint">
                          {mapPresentation === "graph"
                            ? "点击节点，继续向下探索"
                            : "先看依据，再决定是否深入"}
                        </span>
                      </div>
                      {mapPresentation === "graph" && (
                        <button
                          className="map-scope-toggle"
                          onClick={() =>
                            setMaxRelations((old) => (old === 0 ? 3 : 0))
                          }
                        >
                          {maxRelations === 0 ? "切回概览" : "显示全部关系"}
                        </button>
                      )}
                      {mapPresentation === "graph" ? (
                        <Suspense
                          fallback={
                            <div className="graph-loading" role="status">
                              <LoaderCircle size={20} className="spin" />
                              正在准备可交互的领域地图…
                            </div>
                          }
                        >
                          <FieldGraph
                            theme={theme}
                            field={field}
                            explored={explored}
                            onExplore={exploreNode}
                            showPrerequisites={showPrerequisites}
                            showSubfields={showSubfields}
                            minConfidence={minConfidence}
                            depth={depth}
                            maxRelations={maxRelations}
                            busy={busy}
                          />
                        </Suspense>
                      ) : (
                        <section className="relations-panel">
                          <div className="relation-tabs">
                            <button
                              className={
                                relationTab === "subfields" ? "active" : ""
                              }
                              onClick={() => setRelationTab("subfields")}
                            >
                              研究分支 <b>{field.subfields.length}</b>
                            </button>
                            <button
                              className={
                                relationTab === "prerequisites" ? "active" : ""
                              }
                              onClick={() => setRelationTab("prerequisites")}
                            >
                              前置领域 <b>{field.prerequisites.length}</b>
                            </button>
                          </div>
                          <RelationEvidenceList
                            field={field}
                            kind={relationTab}
                            minConfidence={minConfidence}
                            onExplore={exploreNode}
                          />
                        </section>
                      )}
                      <details className="map-options">
                        <summary>
                          <Layers size={13} />
                          图谱与关系筛选
                          <ChevronRight size={13} />
                        </summary>
                        <div>
                          <label>
                            <input
                              type="checkbox"
                              checked={showPrerequisites}
                              onChange={(event) =>
                                setShowPrerequisites(event.target.checked)
                              }
                            />
                            显示前置领域
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              checked={showSubfields}
                              onChange={(event) =>
                                setShowSubfields(event.target.checked)
                              }
                            />
                            显示研究分支
                          </label>
                          <label>
                            展开层数
                            <select
                              aria-label="展开层数"
                              value={depth}
                              onChange={(event) =>
                                setDepth(Number(event.target.value))
                              }
                            >
                              <option value={1}>一层</option>
                              <option value={2}>两层 · 仅已探索领域</option>
                            </select>
                          </label>
                          <label className="strength-filter">
                            关系判断最低值{" "}
                            <span>{Math.round(minConfidence * 100)}%</span>
                            <input
                              aria-label="关系判断最低值"
                              type="range"
                              min={0}
                              max={1}
                              step={0.05}
                              value={minConfidence}
                              onChange={(event) =>
                                setMinConfidence(Number(event.target.value))
                              }
                            />
                          </label>
                          <p>
                            模型判断不是统计概率；筛选只用于减少图中关系，不代表证据已经验证。
                          </p>
                        </div>
                      </details>
                    </section>
                    <DetailPanel
                      field={field}
                      onExplore={exploreNode}
                      busy={busy}
                      onSavePaper={addPaper}
                      savedPaperIds={savedPaperIds}
                    />
                  </div>
                  <footer className="workspace-footer">
                    <span>
                      <ShieldCheck size={13} />
                      {field.paper_source === "demo"
                        ? "预设领域示例，真实书目；不调用外部服务。"
                        : "基于候选论文的书目与摘要分析，关系仍需结合原文核对。"}
                    </span>
                    <span>
                      {field.candidate_count} 篇候选 ·{" "}
                      {field.evidence_papers?.length ?? 0} 篇关系支持书目
                    </span>
                  </footer>
                </>
              ) : (
                <div className="initial-analysis">
                  <Compass size={38} />
                  <h1>正在准备你的研究地图</h1>
                  <p>检索返回后，你可以先看论文，再等待领域关系和阅读建议。</p>
                </div>
              )}
            </>
          )}
        </main>
      </div>
      {(busy || resolving) && (
        <div className="loading-toast" role="status">
          <span className="loading-orbit">
            <LoaderCircle size={20} className="spin" />
          </span>
          <div>
            <strong>
              {resolving ? "先识别你的研究方向" : `正在探索 ${loadingName}`}
            </strong>
            <span>
              {resolving
                ? "把问题转为检索范围，并检查可能匹配的论文…"
                : loadingStage}
            </span>
            <small>
              已用时 {elapsed} 秒 ·{" "}
              {resolving
                ? "离开当前页面会取消方向识别"
                : "可以先切换页面，分析不会抢占当前视图"}
            </small>
          </div>
          <button
            className="text-button"
            onClick={() =>
              resolving
                ? dismissResolution()
                : requests.cancel(activeRequest.current)
            }
          >
            取消
          </button>
        </div>
      )}
      {toast && (
        <div className="action-toast" role="status">
          <Check size={16} />
          {toast}
          <button
            className="icon-button"
            aria-label="关闭操作提示"
            onClick={() => setToast("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {exportDocument && (
        <div className="modal-backdrop" onClick={() => setExportDocument(null)}>
          <section
            className="help-modal export-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="export-title"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="close-modal icon-button"
              autoFocus
              aria-label="关闭导出"
              onClick={() => setExportDocument(null)}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">
              <FileText size={15} /> 可带走的研究材料
            </span>
            <h2 id="export-title">{exportDocument.title}</h2>
            <p>
              {exportDocument.format === "json"
                ? "结构化地图供其他工具继续处理。"
                : "保存或复制这份带论文出处的材料，继续你的阅读与讨论。"}
              文件可能包含研究主题和私人笔记，请按需分享。
            </p>
            <textarea
              aria-label={
                exportDocument.format === "json" ? "地图 JSON" : "导出文档内容"
              }
              readOnly
              value={exportDocument.content}
              onFocus={(event) => event.currentTarget.select()}
            />
            <div className="export-buttons">
              <a
                className="download-json"
                href={exportUrl}
                download={exportDocument.filename}
              >
                <Download size={16} />
                下载 {exportDocument.format === "json" ? "JSON" : "Markdown"}
              </a>
              <button
                className="secondary-button"
                onClick={() => {
                  void navigator.clipboard
                    ?.writeText(exportDocument.content)
                    .then(() => setExportCopied(true))
                    .catch(() => setToast("也可以选中上方文本直接复制。"));
                }}
              >
                {exportCopied ? <Check size={16} /> : <Copy size={16} />}
                {exportCopied ? "已复制" : "复制内容"}
              </button>
            </div>
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
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="close-modal icon-button"
              autoFocus
              aria-label="关闭使用指南"
              onClick={() => setShowHelp(false)}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">
              <Compass size={15} /> 开始你的研究
            </span>
            <h2 id="help-title">从一个好问题，到下一篇论文</h2>
            <ol>
              <li>
                <strong>写下研究问题，确认方向</strong>
                <p>
                  中文、简称都可以。遇到多种可能，选择适合自己意图的方向后再开始分析。
                </p>
              </li>
              <li>
                <strong>查看地图，也查看依据</strong>
                <p>
                  前置领域帮助补知识，研究分支帮助找方向。切换“方向与证据”，展开支持书目并核对来源。
                </p>
              </li>
              <li>
                <strong>把论文留在自己的清单里</strong>
                <p>
                  加入阅读清单、标记已读、记录疑问。研究简报和阅读笔记均可导出
                  Markdown。
                </p>
              </li>
            </ol>
            <div className="help-modes">
              <h3>哪种模式适合现在？</h3>
              <p>
                <b>自动检索：</b>
                先尝试真实论文服务；仅对已知的示例领域提供明确标识的离线回退。
                <br />
                <b>实时检索：</b>使用真实论文服务，失败时直接说明。
                <br />
                <b>离线示例：</b>体验 NHSE
                及预设分支；书目已核对，关系和阅读排序为预设。
              </p>
              <p>
                实时分析会向检索与模型服务发送研究问题、候选论文书目和摘要。当前不读取论文全文，也不生成经过验证的系统综述。
              </p>
              <p>
                研究记录和阅读笔记只保存在当前浏览器；换设备不会自动同步。清除探索记录不会删除阅读清单。
              </p>
              <span className="service-note">
                {(health?.llm_ready ?? health?.llm_configured)
                  ? "此环境已配置模型分析，可尝试实时研究。"
                  : "此环境未配置完整模型分析。离线示例与明确关键词的论文检索仍可使用。"}
              </span>
            </div>
            <button className="primary" onClick={() => setShowHelp(false)}>
              开始研究
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
