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
  Languages,
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
import { useTranslation } from "react-i18next";
import { useLocale } from "./i18n";
import { normalizeLanguage } from "./types";
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
  restoreLibraryItem,
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
  Language,
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
  language: Language;
};
function nodesForMode(
  snapshots: Record<string, FieldNode>,
  mode: Mode,
  researchQuestion?: string | null,
  language: Language = "zh-CN",
) {
  const question = normalizeResearchQuestion(researchQuestion);
  const result: Record<string, FieldNode> = {};
  for (const [key, node] of Object.entries(snapshots)) {
    if (!key.startsWith(`${mode}:`)) continue;
    if (normalizeLanguage(node.language) !== language) continue;
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
function shortDate(value?: string, language = "zh-CN") {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "";
  return new Intl.DateTimeFormat(
    language.startsWith("en") ? "en-US" : "zh-CN",
    {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    },
  ).format(new Date(value));
}
function sourceLabel(field: FieldNode, translate: (key: string) => string) {
  if (field.paper_source === "demo") return translate("source.demo");
  if (field.phase !== "complete") return translate("source.incomplete");
  if (field.analysis_source === "mock") return translate("source.mock");
  return translate("source.openalex");
}
function friendlyError(error: unknown, translate: (key: string) => string) {
  if (!(error instanceof Error)) return translate("errors.generic");
  if (error.name === "TimeoutError") return translate("errors.timeout");
  if (error.message === "Failed to fetch") return translate("errors.network");
  return error.message;
}

export default function App() {
  const { t, i18n } = useTranslation("app");
  const { language, setLanguage } = useLocale();
  const languageRef = useRef(language);
  languageRef.current = language;
  const [initial] = useState(loadSession);
  const restored =
    initial.snapshots[
      requestKey(
        initial.current,
        initial.mode,
        initial.current_research_question,
        initial.current_language,
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
      initial.current_language,
    ),
  );
  const [requests] = useState(() => new ExplorationRequests(exploreField));
  const activeRequest = useRef("");
  const historyGeneration = useRef(0);
  const failedOperation = useRef<"resolve" | "explore">("resolve");
  const failedMode = useRef<Mode>(initial.mode);
  const failedLanguage = useRef<Language>(language);
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
  const [loadingStage, setLoadingStage] = useState("loading.workspace");
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
  const [confirmHistoryClear, setConfirmHistoryClear] = useState(false);
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
  const presentationChosen = useRef(false);
  const [health, setHealth] = useState<{
    llm_ready?: boolean;
    llm_configured?: boolean;
    openalex_key_configured?: boolean;
  } | null>(null);
  const [library, setLibrary] = useState<SavedPaper[]>(loadLibrary);
  const [removedPaper, setRemovedPaper] = useState<{
    item: SavedPaper;
    index: number;
  } | null>(null);
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
      ?.setAttribute("content", theme === "dark" ? "#121b23" : "#f6f7f9");
    try {
      localStorage.setItem("field-navigator-theme", theme);
    } catch {
      /* Appearance remains usable without persistence. */
    }
  }, [theme]);
  useEffect(() => {
    document.documentElement.lang = language;
    document.title = `Field Navigator · ${t("brand.tagline")}`;
    document
      .querySelector('meta[name="description"]')
      ?.setAttribute("content", t("brand.description"));
  }, [language, t]);
  useEffect(() => {
    const compact = window.matchMedia("(max-width: 1099px)");
    const update = () => {
      if (!presentationChosen.current)
        setMapPresentation(compact.matches ? "list" : "graph");
    };
    update();
    compact.addEventListener("change", update);
    return () => compact.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    // A newly selected page or research topic starts at its heading. Refreshing
    // another phase of the same topic does not interrupt the reading position.
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [view, field?.name, field?.research_question]);
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
      current_language: normalizeLanguage(field?.language),
      mode,
      snapshots,
      trail,
      trail_contexts: trailContexts,
    });
    setStorageWarning(ok ? "" : t("errors.sessionStorage"));
  }, [history, field, mode, snapshots, trail, trailContexts, t]);
  useEffect(() => {
    setLibraryWarning(saveLibrary(library) ? "" : t("errors.libraryStorage"));
  }, [library, t]);
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
    if (!showHelp && !exportDocument && !confirmHistoryClear) return;
    const previousOverflow = document.body.style.overflow;
    const background = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".app-header, .workspace, .skip-link",
      ),
      (element) => ({ element, inert: element.inert }),
    );
    background.forEach(({ element }) => {
      element.inert = true;
    });
    document.body.style.overflow = "hidden";
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowHelp(false);
        setExportDocument(null);
        setConfirmHistoryClear(false);
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
      background.forEach(({ element, inert }) => {
        element.inert = inert;
      });
      if (dialogReturnFocus.current?.isConnected)
        dialogReturnFocus.current.focus();
    };
  }, [showHelp, exportDocument, confirmHistoryClear]);

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
        language?: Language;
        researchQuestion?: string | null;
      } = {},
    ) => {
      const selectedMode = options.mode ?? modeRef.current;
      const selectedLanguage = options.language ?? languageRef.current;
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
        normalizeLanguage(currentRef.current.language) === selectedLanguage &&
        completedMode.current === selectedMode;
      const researchQuestion = hasExplicitQuestion
        ? explicitQuestion
        : sameCurrentField
          ? normalizeResearchQuestion(currentRef.current?.research_question) ||
            undefined
          : undefined;
      const key = requestKey(
        name,
        selectedMode,
        researchQuestion,
        selectedLanguage,
      );
      activeRequest.current = key;
      modeRef.current = selectedMode;
      setMode(selectedMode);
      setExplored(
        nodesForMode(
          snapshotsRef.current,
          selectedMode,
          researchQuestion,
          selectedLanguage,
        ),
      );
      failedMode.current = selectedMode;
      failedLanguage.current = selectedLanguage;
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
            normalizeLanguage(previous.language),
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
      setLoadingStage("loading.savedStages");
      setPending((old) => ({
        ...old,
        [key]: {
          name,
          mode: selectedMode,
          researchQuestion,
          language: selectedLanguage,
        },
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
                event.stage === "search" ? "loading.search" : "loading.cached",
              );
            if (event.type === "partial") {
              displayed.current = event.field;
              setField(event.field);
              setLoadingStage(
                event.stage === "papers" ? "loading.papers" : "loading.map",
              );
            }
          },
          researchQuestion,
          selectedLanguage,
        );
        if (generation !== historyGeneration.current) return;
        if (result.phase === "complete") {
          setSnapshots((old) => ({
            ...old,
            [requestKey(
              result.name,
              selectedMode,
              researchQuestion,
              selectedLanguage,
            )]: result,
          }));
          setHistory((old) =>
            [
              ...old.filter(
                (entry) =>
                  requestKey(
                    entry.name,
                    entry.mode,
                    entry.research_question,
                    entry.language,
                  ) !==
                  requestKey(
                    result.name,
                    selectedMode,
                    researchQuestion,
                    selectedLanguage,
                  ),
              ),
              {
                name: result.name,
                parent,
                mode: selectedMode,
                language: selectedLanguage,
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
                language: selectedLanguage,
                error: friendlyError(cause, t),
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
              normalizeLanguage(previous.language),
            ),
          );
        }
        if (!(cause instanceof Error && cause.name === "AbortError"))
          setError(friendlyError(cause, t));
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
    [requests, t],
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
  function startNewResearch() {
    goHome();
    setQuery("");
    modeRef.current = "auto";
    setMode("auto");
    setTimeout(() => document.getElementById("research-query")?.focus(), 0);
  }
  useEffect(() => {
    if (view !== "library") return;
    const handleNewResearch = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key !== "k") return;
      if (
        event.defaultPrevented ||
        event.isComposing ||
        (event.target instanceof HTMLElement &&
          event.target.closest('input, textarea, [contenteditable="true"]')) ||
        document.querySelector('[aria-modal="true"]') ||
        document.querySelector<HTMLElement>(".app-header")?.inert
      )
        return;
      event.preventDefault();
      startNewResearch();
    };
    window.addEventListener("keydown", handleNewResearch);
    return () => window.removeEventListener("keydown", handleNewResearch);
  }, [view]);
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
      setError(t("errors.shortQuery"));
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
      const result = await resolveQuery(
        input,
        selectedMode,
        controller.signal,
        languageRef.current,
      );
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
        setError(friendlyError(cause, t));
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
        normalizeLanguage(current.language),
      ),
    );
    setQuery(current.name);
    setView("map");
  }
  function addPaper(core: CorePaper, fieldName: string) {
    const existing = isSavedPaper(core.paper, getSavedPaperIds(library));
    if (!existing && library.length >= MAX_LIBRARY_ITEMS) {
      setToast(t("toast.libraryFull", { count: MAX_LIBRARY_ITEMS }));
      return;
    }
    setLibrary((old) => addToLibrary(old, core, fieldName));
    setToast(existing ? t("toast.paperSourceAdded") : t("toast.paperAdded"));
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
        ? t("toast.readingStartSkipped", { added, skipped })
        : added
          ? t("toast.readingStartAdded", { count: added })
          : t("toast.readingStartExisting"),
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
    if (!clearSession()) setStorageWarning(t("errors.clearStorage"));
    setToast(t("toast.historyCleared"));
  }
  function removePaper(id: string) {
    const index = library.findIndex((item) => item.id === id);
    if (index < 0) return;
    setRemovedPaper({ item: library[index], index });
    setLibrary((old) => removeLibraryItem(old, id));
    setToast(t("toast.paperRemoved"));
  }
  function undoRemovePaper() {
    if (!removedPaper) return;
    if (isSavedPaper(removedPaper.item.paper, savedPaperIds)) {
      setRemovedPaper(null);
      setToast(t("toast.paperRestoredAlready"));
      return;
    }
    if (library.length >= MAX_LIBRARY_ITEMS) {
      setToast(t("toast.libraryFullUndo"));
      return;
    }
    setLibrary((old) =>
      restoreLibraryItem(old, removedPaper.item, removedPaper.index),
    );
    setRemovedPaper(null);
    setToast(t("toast.paperRestored"));
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
        title: t("dialogs.briefTitle"),
        content: buildResearchBrief(field, Object.values(explored), language),
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
      <a className="skip-link" href="#research-workspace">
        {t("brand.skipToResearch")}
      </a>
      <header className="app-header">
        <button
          className="brand"
          onClick={goHome}
          aria-label={t("brand.homeAria")}
        >
          <span className="brand-symbol">
            <Compass size={24} strokeWidth={1.7} />
          </span>
          <span>
            Field Navigator<small>{t("brand.tagline")}</small>
          </span>
        </button>
        {view === "map" && (
          <SearchBar
            query={query}
            setQuery={setQuery}
            mode={mode}
            setMode={changeMode}
            busy={resolving}
            onSearch={() => void submitQuery()}
          />
        )}
        {view === "library" && (
          <span
            className="header-research-shortcut"
            title={t("header.newResearchShortcut")}
          >
            <kbd>Ctrl K</kbd> {t("header.newResearchShortcutLabel")}
          </span>
        )}
        <div className="header-actions">
          <label className="language-switcher">
            <Languages size={16} aria-hidden="true" />
            <span className="sr-only">{t("language.label")}</span>
            <select
              aria-label={t("language.label")}
              value={language}
              onChange={(event) => {
                const next = event.target.value as Language;
                dismissResolution();
                setChosenDirection(null);
                if (!setLanguage(next))
                  setToast(
                    i18n.getFixedT(next, "app")("language.preferenceNotSaved"),
                  );
              }}
            >
              <option value="zh-CN" lang="zh-CN">
                简体中文
              </option>
              <option value="en" lang="en">
                English
              </option>
            </select>
          </label>
          <span className="private-badge">
            <ShieldCheck size={14} /> {t("header.privateWorkspace")}
          </span>
          <button
            className="theme-toggle icon-button"
            aria-label={t(
              theme === "light" ? "header.toggleDark" : "header.toggleLight",
            )}
            onClick={() =>
              setTheme((old) => (old === "light" ? "dark" : "light"))
            }
          >
            {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <button
            className="help-button"
            aria-label={t("header.helpAria")}
            onClick={() => {
              dialogReturnFocus.current =
                document.activeElement as HTMLElement | null;
              setShowHelp(true);
            }}
          >
            <Info size={17} />
            <span>{t("header.help")}</span>
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="workspace-label">
            <Layers size={16} />
            <span>
              {t("sidebar.workspace")}
              <small>{t("sidebar.workspaceSubtitle")}</small>
            </span>
          </div>
          <button
            className={`new-exploration ${view === "home" ? "selected" : ""}`}
            aria-current={view === "home" ? "page" : undefined}
            onClick={startNewResearch}
          >
            <Plus size={17} /> {t("sidebar.newQuestion")}
          </button>
          <button
            className={`library-nav ${view === "library" ? "selected" : ""}`}
            aria-current={view === "library" ? "page" : undefined}
            onClick={openLibrary}
          >
            <Bookmark size={17} /> {t("sidebar.readingList")}{" "}
            <b>{library.length}</b>
          </button>
          <div className="sidebar-section-label">
            <span>
              <History size={13} /> {t("sidebar.recent")}
            </span>
            <b>{history.length}</b>
          </div>
          <nav className="history-list" aria-label={t("sidebar.historyAria")}>
            {history.length ? (
              [...history].reverse().map((entry) => (
                <button
                  key={requestKey(
                    entry.name,
                    entry.mode,
                    entry.research_question,
                    entry.language,
                  )}
                  title={entry.research_question || entry.name}
                  className={`history-item ${view === "map" && field && requestKey(field.name, completedMode.current, field.research_question, normalizeLanguage(field.language)) === requestKey(entry.name, entry.mode, entry.research_question, entry.language) ? "selected" : ""}`}
                  onClick={() => {
                    dismissResolution();
                    setChosenDirection(null);
                    void explore(entry.name, {
                      resetPath: true,
                      mode: entry.mode,
                      language: normalizeLanguage(entry.language),
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
                        ? t("sidebar.offline")
                        : t("sidebar.paperSearch")}
                      {" · "}
                      {t(
                        normalizeLanguage(entry.language) === "en"
                          ? "language.codeEnglish"
                          : "language.codeChinese",
                      )}
                      {entry.created_at
                        ? ` · ${shortDate(entry.created_at, i18n.language)}`
                        : ` · ${t("sidebar.resume")}`}
                    </small>
                  </span>
                </button>
              ))
            ) : (
              <div className="sidebar-empty">
                <Compass size={23} />
                <p>{t("sidebar.emptyHistory")}</p>
              </div>
            )}
          </nav>
          {(countPending > 0 || Object.keys(backgroundErrors).length > 0) && (
            <nav
              className="pending-list"
              aria-label={t("sidebar.backgroundAnalysis")}
            >
              <div className="sidebar-section-label">
                {t("sidebar.backgroundAnalysis")} <b>{countPending}</b>
              </div>
              {Object.entries(pending).map(([key, job]) => (
                <div className="pending-job" key={key}>
                  <button
                    onClick={() =>
                      void explore(job.name, {
                        mode: job.mode,
                        language: job.language,
                        researchQuestion: job.researchQuestion ?? null,
                      })
                    }
                  >
                    <LoaderCircle size={14} className="spin" />
                    <span>
                      {job.name}
                      <small>{t("sidebar.viewProgress")}</small>
                    </span>
                  </button>
                  <button
                    className="icon-button"
                    aria-label={t("sidebar.cancelAnalysis", { name: job.name })}
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
                      language: job.language,
                      researchQuestion: job.researchQuestion ?? null,
                    })
                  }
                >
                  <Info size={14} />
                  <span>
                    {job.name}
                    <small>{t("sidebar.failedRetry")}</small>
                  </span>
                </button>
              ))}
            </nav>
          )}
          <div className="sidebar-bottom">
            <div className="local-status">
              <Database size={12} />
              <span>{t("sidebar.localRecords")}</span>
              {history.length > 0 && (
                <button
                  className="icon-button"
                  aria-label={t("sidebar.clearHistoryAria")}
                  title={t("sidebar.clearHistoryTitle")}
                  onClick={() => {
                    dialogReturnFocus.current =
                      document.activeElement as HTMLElement | null;
                    setConfirmHistoryClear(true);
                  }}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          </div>
        </aside>
        <main
          id="research-workspace"
          tabIndex={-1}
          className={`main-workspace view-${view}`}
        >
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
                      language: failedLanguage.current,
                      researchQuestion: failedResearchQuestion.current ?? null,
                    });
                  else void submitQuery();
                }}
              >
                {t("status.retry")}
              </button>
              <button
                onClick={() => {
                  dismissResolution();
                  void explore(ROOT, { mode: "demo", resetPath: true });
                }}
              >
                {t("status.tryDemo")}
              </button>
              <button
                className="icon-button"
                aria-label={t("status.closeError")}
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
                        language: normalizeLanguage(previousEntry.language),
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
              onRemove={removePaper}
              onExplore={goHome}
              onUndoRemove={undoRemovePaper}
              canUndoRemove={!!removedPaper}
              onClear={() => {
                setRemovedPaper(null);
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
                  title: t("dialogs.readingListTitle"),
                  content: exportLibraryMarkdown(library, language),
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
                <nav className="breadcrumbs" aria-label={t("navigation.path")}>
                  <button
                    className="icon-button"
                    aria-label={t("navigation.back")}
                    disabled={trail.length < 2}
                    onClick={() =>
                      exploreNode(trail[trail.length - 2], trail.length - 2)
                    }
                  >
                    <ArrowLeft size={16} />
                  </button>
                  <button onClick={goHome}>{t("navigation.root")}</button>
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
                    <FileText size={14} /> {t("navigation.exportBrief")}
                  </button>
                  <button
                    className="icon-button"
                    title={t("navigation.exportMapTitle")}
                    aria-label={t("navigation.exportMapAria")}
                    disabled={!field || field.phase !== "complete"}
                    onClick={() =>
                      openExport({
                        title: t("navigation.exportMapTitle"),
                        content: serializeMap(
                          Object.values(explored),
                          field?.id,
                          language,
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
                        <Compass size={14} /> {t("field.map")}
                      </span>
                      <span
                        className={`source-badge ${field.paper_source === "demo" ? "demo" : ""}`}
                      >
                        {sourceLabel(field, t)}
                      </span>
                    </div>
                    <h1>{field.name}</h1>
                    {chosenDirection &&
                      chosenDirection.query === field.name && (
                        <p className="chosen-scope">
                          <Compass size={13} /> {t("field.selectedScope")}
                          {chosenDirection.summary}
                        </p>
                      )}
                    {field.research_question && (
                      <p
                        className="research-question"
                        title={field.research_question}
                      >
                        <span>{t("field.originalQuestion")}</span>
                        {shortQuestion(field.research_question)}
                      </p>
                    )}
                    <p
                      className="field-summary"
                      lang={normalizeLanguage(field.language)}
                    >
                      {field.summary}
                    </p>
                    <div className="field-stats">
                      <span>
                        <BookOpen size={14} />
                        {field.phase === "complete"
                          ? t("field.readingEntry", {
                              count: field.core_papers.length,
                            })
                          : t("field.initialPapers", {
                              count: field.core_papers.length,
                            })}
                      </span>
                      <span>
                        <GitBranch size={14} />
                        {t("field.branches", { count: field.subfields.length })}
                      </span>
                      <span>
                        <Layers size={14} />
                        {t("field.prerequisites", {
                          count: field.prerequisites.length,
                        })}
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
                          ? t("field.savedAt", {
                              date: shortDate(field.created_at, i18n.language),
                            })
                          : busy
                            ? t("field.analyzing")
                            : t("field.partial")}
                      </span>
                      <button
                        className="refresh-button"
                        disabled={
                          !!pending[
                            requestKey(
                              field.name,
                              mode,
                              field.research_question,
                              normalizeLanguage(field.language),
                            )
                          ]
                        }
                        onClick={() =>
                          void explore(field.name, {
                            refresh: field.phase === "complete",
                            language: normalizeLanguage(field.language),
                            researchQuestion: field.research_question ?? null,
                          })
                        }
                      >
                        <RotateCw size={13} />
                        {field.phase === "complete"
                          ? t("field.update")
                          : t("field.retry")}
                      </button>
                    </div>
                  </section>
                  {normalizeLanguage(field.language) !== language && (
                    <div className="language-notice" role="note">
                      <Languages size={16} aria-hidden="true" />
                      <span>
                        {t("language.savedContent", {
                          language: t(
                            normalizeLanguage(field.language) === "en"
                              ? "language.english"
                              : "language.chinese",
                          ),
                        })}
                      </span>
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() =>
                          void explore(field.name, {
                            language,
                            mode: completedMode.current,
                            resetPath: true,
                            researchQuestion: field.research_question ?? null,
                          })
                        }
                      >
                        {t("language.analyzeIn", {
                          language: t(
                            language === "en"
                              ? "language.english"
                              : "language.chinese",
                          ),
                        })}
                      </button>
                    </div>
                  )}
                  {relevantWarnings.length > 0 && (
                    <details
                      className="analysis-notice"
                      open={field.phase !== "complete" && !busy}
                    >
                      <summary>
                        <Info size={14} />
                        <span>
                          {field.phase !== "complete" && !busy
                            ? t("field.pendingNotice")
                            : field.paper_source === "demo"
                              ? t("field.demoNotice")
                              : t("field.limitations")}
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
                    <section
                      className="reading-next"
                      aria-label={t("field.readingStartAria")}
                    >
                      <span className="reading-next-icon">
                        <Bookmark size={18} />
                      </span>
                      <div>
                        <h2>
                          {field.phase === "complete"
                            ? t("field.readingStart")
                            : t("field.readingStartPartial")}
                        </h2>
                        <p>{firstPaper.paper.title}</p>
                        <small>{t("field.readingStartHint")}</small>
                      </div>
                      <button
                        className="secondary-button"
                        onClick={saveReadingStart}
                      >
                        <Plus size={15} />
                        {t("field.saveFirst", {
                          count: Math.min(3, field.core_papers.length),
                        })}
                      </button>
                    </section>
                  )}
                  <nav
                    className="workspace-section-nav"
                    aria-label={t("field.researchContents")}
                  >
                    <a href="#research-directions">
                      <GitBranch size={15} /> {t("field.directionsEvidence")}
                    </a>
                    <a href="#reading-entries">
                      <BookOpen size={15} /> {t("field.corePapers")} ·{" "}
                      {field.core_papers.length}
                    </a>
                  </nav>
                  <div className="content-columns">
                    <section
                      id="research-directions"
                      className="map-column"
                      aria-label={t("field.mapDirectionsEvidence")}
                      tabIndex={-1}
                    >
                      <div className="map-view-toolbar">
                        <div
                          className="view-switch"
                          role="group"
                          aria-label={t("field.relationCategory")}
                        >
                          <button
                            aria-pressed={mapPresentation === "graph"}
                            className={
                              mapPresentation === "graph" ? "active" : ""
                            }
                            onClick={() => {
                              presentationChosen.current = true;
                              setMapPresentation("graph");
                            }}
                          >
                            <Network size={14} /> {t("field.viewMap")}
                          </button>
                          <button
                            aria-pressed={mapPresentation === "list"}
                            className={
                              mapPresentation === "list" ? "active" : ""
                            }
                            onClick={() => {
                              presentationChosen.current = true;
                              setMapPresentation("list");
                            }}
                          >
                            <List size={14} /> {t("field.list")}
                          </button>
                        </div>
                        <span className="map-view-hint">
                          {mapPresentation === "graph"
                            ? t("field.clickNode")
                            : t("field.inspectEvidence")}
                        </span>
                      </div>
                      {mapPresentation === "graph" && (
                        <button
                          className="map-scope-toggle"
                          onClick={() =>
                            setMaxRelations((old) => (old === 0 ? 3 : 0))
                          }
                        >
                          {maxRelations === 0
                            ? t("field.overview")
                            : t("field.allRelations")}
                        </button>
                      )}
                      {mapPresentation === "graph" ? (
                        <Suspense
                          fallback={
                            <div className="graph-loading" role="status">
                              <LoaderCircle size={20} className="spin" />
                              {t("loading.graph")}
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
                          <div
                            className="relation-tabs"
                            role="tablist"
                            aria-label={t("field.relationCategory")}
                            onKeyDown={(event) => {
                              if (
                                ![
                                  "ArrowLeft",
                                  "ArrowRight",
                                  "Home",
                                  "End",
                                ].includes(event.key)
                              )
                                return;
                              event.preventDefault();
                              const next =
                                event.key === "Home"
                                  ? "subfields"
                                  : event.key === "End"
                                    ? "prerequisites"
                                    : relationTab === "subfields"
                                      ? "prerequisites"
                                      : "subfields";
                              setRelationTab(next);
                              document
                                .getElementById(`relation-tab-${next}`)
                                ?.focus();
                            }}
                          >
                            <button
                              id="relation-tab-subfields"
                              role="tab"
                              aria-selected={relationTab === "subfields"}
                              aria-controls="relation-panel"
                              tabIndex={relationTab === "subfields" ? 0 : -1}
                              className={
                                relationTab === "subfields" ? "active" : ""
                              }
                              onClick={() => setRelationTab("subfields")}
                            >
                              {t("field.subfields")}{" "}
                              <b>{field.subfields.length}</b>
                            </button>
                            <button
                              id="relation-tab-prerequisites"
                              role="tab"
                              aria-selected={relationTab === "prerequisites"}
                              aria-controls="relation-panel"
                              tabIndex={
                                relationTab === "prerequisites" ? 0 : -1
                              }
                              className={
                                relationTab === "prerequisites" ? "active" : ""
                              }
                              onClick={() => setRelationTab("prerequisites")}
                            >
                              {t("field.prerequisiteFields")}{" "}
                              <b>{field.prerequisites.length}</b>
                            </button>
                          </div>
                          <div
                            id="relation-panel"
                            role="tabpanel"
                            aria-labelledby={`relation-tab-${relationTab}`}
                            tabIndex={0}
                          >
                            <RelationEvidenceList
                              field={field}
                              kind={relationTab}
                              minConfidence={minConfidence}
                              onExplore={exploreNode}
                              onResetFilters={() => setMinConfidence(0)}
                            />
                          </div>
                        </section>
                      )}
                      <details className="map-options">
                        <summary>
                          <Layers size={13} />
                          {t("field.graphOptions")}
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
                            {t("field.showPrerequisites")}
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              checked={showSubfields}
                              onChange={(event) =>
                                setShowSubfields(event.target.checked)
                              }
                            />
                            {t("field.showSubfields")}
                          </label>
                          <label>
                            {t("field.depth")}
                            <select
                              aria-label={t("field.depth")}
                              value={depth}
                              onChange={(event) =>
                                setDepth(Number(event.target.value))
                              }
                            >
                              <option value={1}>{t("field.oneLevel")}</option>
                              <option value={2}>{t("field.twoLevels")}</option>
                            </select>
                          </label>
                          <label className="strength-filter">
                            {t("field.confidence")}{" "}
                            <span>{Math.round(minConfidence * 100)}%</span>
                            <input
                              aria-label={t("field.confidence")}
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
                          <p>{t("field.confidenceBoundary")}</p>
                        </div>
                      </details>
                    </section>
                    <div
                      id="reading-entries"
                      className="reading-entries"
                      aria-label={t("field.corePapers")}
                      role="region"
                      tabIndex={-1}
                    >
                      <DetailPanel
                        field={field}
                        onExplore={exploreNode}
                        busy={busy}
                        onSavePaper={addPaper}
                        savedPaperIds={savedPaperIds}
                      />
                    </div>
                  </div>
                  <footer className="workspace-footer">
                    <span>
                      <ShieldCheck size={13} />
                      {field.paper_source === "demo"
                        ? t("field.demoFooter")
                        : t("field.liveFooter")}
                    </span>
                    <span>
                      {t("field.candidateCount", {
                        candidates: field.candidate_count,
                        evidence: field.evidence_papers?.length ?? 0,
                      })}
                    </span>
                  </footer>
                </>
              ) : (
                <div className="initial-analysis">
                  <Compass size={38} />
                  <h1>
                    {busy
                      ? t("field.preparingTitle")
                      : t("field.incompleteTitle")}
                  </h1>
                  <p>
                    {busy
                      ? t("field.preparingDescription")
                      : t("field.incompleteDescription")}
                  </p>
                </div>
              )}
            </>
          )}
        </main>
      </div>
      <div className="toast-stack">
        {(busy || resolving) && (
          <div className="loading-toast" role="status">
            <span className="loading-orbit">
              <LoaderCircle size={20} className="spin" />
            </span>
            <div>
              <strong>
                {resolving
                  ? t("loading.resolveTitle")
                  : t("loading.exploreDescription", { name: loadingName })}
              </strong>
              <span>
                {resolving ? t("loading.resolveDescription") : t(loadingStage)}
              </span>
              <small>
                {t("loading.elapsed", { seconds: elapsed })} ·{" "}
                {resolving
                  ? t("loading.resolveLeave")
                  : t("loading.exploreContinue")}
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
              {t("loading.cancel")}
            </button>
          </div>
        )}
        {toast && (
          <div className="action-toast" role="status">
            <Check size={16} />
            <span>{toast}</span>
            <button
              className="icon-button"
              aria-label={t("status.toastClose")}
              onClick={() => setToast("")}
            >
              <X size={14} />
            </button>
          </div>
        )}
      </div>
      {confirmHistoryClear && (
        <div
          className="modal-backdrop"
          onClick={() => setConfirmHistoryClear(false)}
        >
          <section
            className="help-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="clear-history-title"
            aria-describedby="clear-history-description"
            onClick={(event) => event.stopPropagation()}
          >
            <span className="eyebrow">
              <History size={15} /> {t("dialogs.clearHistoryEyebrow")}
            </span>
            <h2 id="clear-history-title">{t("dialogs.clearHistoryTitle")}</h2>
            <p id="clear-history-description">
              {t("dialogs.clearHistoryDescription")}
            </p>
            <div className="export-buttons">
              <button
                className="secondary-button"
                autoFocus
                onClick={() => setConfirmHistoryClear(false)}
              >
                {t("dialogs.keepRecords")}
              </button>
              <button
                className="secondary-button danger-button"
                onClick={() => {
                  clearHistory();
                  setConfirmHistoryClear(false);
                }}
              >
                {t("dialogs.clearHistory")}
              </button>
            </div>
          </section>
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
              aria-label={t("dialogs.closeExport")}
              onClick={() => setExportDocument(null)}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">
              <FileText size={15} /> {t("dialogs.exportEyebrow")}
            </span>
            <h2 id="export-title">{exportDocument.title}</h2>
            <p>
              {exportDocument.format === "json"
                ? t("dialogs.exportMapDescription")
                : t("dialogs.exportBriefDescription")}{" "}
              {t("dialogs.exportPrivacy")}
            </p>
            <textarea
              aria-label={
                exportDocument.format === "json"
                  ? t("dialogs.mapJson")
                  : t("dialogs.documentContent")
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
                {t("dialogs.download")}{" "}
                {exportDocument.format === "json"
                  ? t("dialogs.json")
                  : t("dialogs.markdown")}
              </a>
              <button
                className="secondary-button"
                onClick={() => {
                  void navigator.clipboard
                    ?.writeText(exportDocument.content)
                    .then(() => setExportCopied(true))
                    .catch(() => setToast(t("toast.copyFallback")));
                }}
              >
                {exportCopied ? <Check size={16} /> : <Copy size={16} />}
                {exportCopied ? t("dialogs.copied") : t("dialogs.copyContent")}
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
              aria-label={t("dialogs.closeHelp")}
              onClick={() => setShowHelp(false)}
            >
              <X size={20} />
            </button>
            <span className="eyebrow">
              <Compass size={15} /> {t("dialogs.helpEyebrow")}
            </span>
            <h2 id="help-title">{t("dialogs.helpTitle")}</h2>
            <ol>
              <li>
                <strong>{t("dialogs.helpStep1Title")}</strong>
                <p>{t("dialogs.helpStep1")}</p>
              </li>
              <li>
                <strong>{t("dialogs.helpStep2Title")}</strong>
                <p>{t("dialogs.helpStep2")}</p>
              </li>
              <li>
                <strong>{t("dialogs.helpStep3Title")}</strong>
                <p>{t("dialogs.helpStep3")}</p>
              </li>
            </ol>
            <div className="help-modes">
              <h3>{t("dialogs.helpModesTitle")}</h3>
              <p>
                <b>{t("dialogs.helpAutoLabel")}</b>
                {t("dialogs.helpAuto")}
                <br />
                <b>{t("dialogs.helpLiveLabel")}</b> {t("dialogs.helpLive")}
                <br />
                <b>{t("dialogs.helpDemoLabel")}</b> {t("dialogs.helpDemo")}
              </p>
              <p>{t("dialogs.helpPrivacy")}</p>
              <p>{t("dialogs.helpLocal")}</p>
              <span className="service-note">
                {(health?.llm_ready ?? health?.llm_configured)
                  ? t("dialogs.serviceReady")
                  : t("dialogs.serviceUnavailable")}
              </span>
            </div>
            <button className="primary" onClick={() => setShowHelp(false)}>
              {t("dialogs.startResearch")}
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
