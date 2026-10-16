import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type NodeProps,
  type Edge,
} from "@xyflow/react";
import {
  ArrowUpRight,
  Check,
  Compass,
  Maximize2,
  Minimize2,
  Network,
  Scan,
  X,
} from "lucide-react";
import type { FieldNode } from "../types";
import { normalizeField as keyOf } from "../state/exploration";
import "./graph.css";
export { normalizeField as keyOf } from "../state/exploration";
type GraphNode = Node<{
  name: string;
  role: "current" | "prerequisite" | "subfield";
  analyzed: boolean;
  paperCount: number | null;
  busy: boolean;
  onExplore: (name: string) => void;
}>;
function FieldCard({ data }: NodeProps<GraphNode>) {
  const { t } = useTranslation("results");
  const disabled = data.busy || data.role === "current";
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <article className={`field-node ${data.role}`}>
        <button
          type="button"
          className="field-node__trigger nodrag"
          aria-label={t("graph.exploreAria", { name: data.name })}
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation();
            if (!disabled) data.onExplore(data.name);
          }}
        >
          <span className="node-eyebrow">
            {data.role === "current" ? (
              <Compass size={13} aria-hidden="true" />
            ) : (
              <span className="node-dot" aria-hidden="true" />
            )}
            {data.role === "current"
              ? t("graph.statusExploring")
              : data.role === "prerequisite"
                ? t("graph.rolePrerequisite")
                : t("graph.roleSubfield")}
          </span>
          <strong title={data.name}>{data.name}</strong>
          <span className="node-bottom">
            <span>
              {data.analyzed ? (
                <>
                  <Check size={11} aria-hidden="true" />{" "}
                  {t("graph.paperCount", { count: data.paperCount ?? 0 })}
                </>
              ) : (
                t("graph.continueExplore")
              )}
            </span>
            <span className="node-action" aria-hidden="true">
              <ArrowUpRight size={16} />
            </span>
          </span>
        </button>
      </article>
      <Handle type="source" position={Position.Right} />
    </>
  );
}
const nodeTypes = { field: FieldCard };
interface Props {
  theme: "light" | "dark";
  field: FieldNode;
  explored: Record<string, FieldNode>;
  onExplore: (name: string) => void;
  showPrerequisites: boolean;
  showSubfields: boolean;
  minConfidence: number;
  depth: number;
  maxRelations?: number;
  busy: boolean;
}
export function buildGraph({
  theme,
  field,
  explored,
  onExplore,
  showPrerequisites,
  showSubfields,
  minConfidence,
  depth,
  maxRelations = 3,
  busy,
}: Props) {
  const nodes: GraphNode[] = [],
    edges: Edge[] = [],
    added = new Set<string>(),
    edgeIds = new Set<string>();
  const center = keyOf(field.name);
  function add(
    name: string,
    role: GraphNode["data"]["role"],
    x: number,
    y: number,
  ) {
    const id = keyOf(name);
    if (added.has(id)) return;
    added.add(id);
    const cached = id === center ? field : explored[id];
    nodes.push({
      id,
      type: "field",
      position: { x, y },
      data: {
        name,
        role,
        analyzed: !!cached,
        paperCount: cached?.core_papers.length ?? null,
        busy,
        onExplore,
      },
      ariaLabel: name,
    });
  }
  function edge(from: string, to: string, pre: boolean) {
    const stroke = pre
      ? "var(--graph-edge-prerequisite)"
      : "var(--graph-edge-subfield)";
    const source = keyOf(from),
      target = keyOf(to),
      id = source + "->" + target;
    if (source === target || edgeIds.has(id)) return;
    edgeIds.add(id);
    edges.push({
      id,
      source,
      target,
      type: "default",
      style: { stroke, strokeWidth: 1.8 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 14,
        height: 14,
        color: stroke,
      },
    });
  }
  add(field.name, "current", 0, 0);
  for (const [kind, enabled] of [
    ["prerequisite", showPrerequisites],
    ["subfield", showSubfields],
  ] as const) {
    if (!enabled) continue;
    const relations = (
      kind === "prerequisite" ? field.prerequisites : field.subfields
    )
      .filter((r) => r.confidence >= minConfidence)
      .slice(0, maxRelations || undefined);
    const direction = kind === "prerequisite" ? -1 : 1;
    relations.forEach((r, i) => {
      add(
        r.name,
        kind,
        direction * 255,
        (i - (relations.length - 1) / 2) * 150,
      );
      if (kind === "prerequisite") edge(r.name, field.name, true);
      else edge(field.name, r.name, false);
    });
    if (depth === 2) {
      let row = 0;
      const second = relations.flatMap((r) => {
        const child = explored[keyOf(r.name)];
        return (
          child
            ? kind === "prerequisite"
              ? child.prerequisites
              : child.subfields
            : []
        )
          .filter((c) => c.confidence >= minConfidence)
          .map((c) => ({ parent: r.name, child: c.name }));
      });
      second.forEach(({ parent, child }) => {
        if (!added.has(keyOf(child)))
          add(
            child,
            kind,
            direction * 560,
            (row++ - (second.length - 1) / 2) * 160,
          );
        if (kind === "prerequisite") edge(child, parent, true);
        else edge(parent, child, false);
      });
    }
  }
  return { nodes, edges };
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

type BackgroundSnapshot = {
  element: HTMLElement;
  inert: boolean;
  inertAttribute: string | null;
  ariaHidden: string | null;
};

function getBackgroundElements(): HTMLElement[] {
  if (typeof document === "undefined") return [];

  const candidates = [
    document.getElementById("root"),
    document.querySelector<HTMLElement>(".app-shell"),
    ...Array.from(document.body.children),
  ];
  const seen = new Set<HTMLElement>();
  return candidates.filter((element): element is HTMLElement => {
    if (!(element instanceof HTMLElement) || seen.has(element)) return false;
    seen.add(element);
    return !element.hasAttribute("data-field-graph-dialog");
  });
}

function getVisibleFocusableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => {
    const style = window.getComputedStyle(element);
    return style.visibility !== "hidden" && style.display !== "none";
  });
}

function GraphCanvas(props: Props) {
  const { t } = useTranslation("results");
  const { fitView } = useReactFlow();
  const [expanded, setExpanded] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const focusReturnPending = useRef(false);
  const titleId = useId();
  const descriptionId = useId();
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  const restoreFocus = () => {
    if (!focusReturnPending.current) return;
    const element =
      previousFocus.current?.isConnected === true
        ? previousFocus.current
        : expandButton.current;
    if (!element?.isConnected || element.hasAttribute("disabled")) return;
    element.focus({ preventScroll: true });
    if (typeof document !== "undefined" && document.activeElement !== element)
      return;
    previousFocus.current = null;
    focusReturnPending.current = false;
  };

  const openExpanded = () => {
    if (typeof document !== "undefined") {
      const active = document.activeElement;
      previousFocus.current = active instanceof HTMLElement ? active : null;
    }
    focusReturnPending.current = true;
    setExpanded(true);
  };

  const closeExpanded = () => setExpanded(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setPrefersReducedMotion(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(
        () =>
          void fitView({
            padding: 0.1,
            duration: prefersReducedMotion ? 0 : 250,
            maxZoom: 1,
          }),
        100,
      );
    });
    if (frame.current) observer.observe(frame.current);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
  }, [fitView, expanded, prefersReducedMotion]);
  const graph = useMemo(
    () => buildGraph(props),
    [
      props.field,
      props.theme,
      props.explored,
      props.showPrerequisites,
      props.showSubfields,
      props.minConfidence,
      props.depth,
      props.maxRelations,
      props.busy,
      props.onExplore,
    ],
  );
  const directionLabels: Record<string, string> = {
    up: t("graph.directionUp"),
    down: t("graph.directionDown"),
    left: t("graph.directionLeft"),
    right: t("graph.directionRight"),
  };
  const layoutKey = graph.nodes.map((n) => n.id).join("|") + props.field.id;
  useEffect(() => {
    const timer = setTimeout(
      () =>
        void fitView({
          padding: 0.1,
          duration: prefersReducedMotion ? 0 : 350,
          maxZoom: 1,
        }),
      50,
    );
    return () => clearTimeout(timer);
  }, [layoutKey, fitView, expanded, prefersReducedMotion]);

  useEffect(() => {
    if (!expanded || typeof document === "undefined") return;

    const snapshots: BackgroundSnapshot[] = getBackgroundElements().map(
      (element) => ({
        element,
        inert: element.inert,
        inertAttribute: element.getAttribute("inert"),
        ariaHidden: element.getAttribute("aria-hidden"),
      }),
    );
    snapshots.forEach(({ element }) => {
      element.inert = true;
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    });

    const body = document.body;
    const previousOverflow = body.style.overflow;
    const previousOverscrollBehavior = body.style.overscrollBehavior;
    body.style.overflow = "hidden";
    body.style.overscrollBehavior = "contain";

    const focusFrame = requestAnimationFrame(() => {
      closeButton.current?.focus({ preventScroll: true });
    });

    const restoreBackground = () => {
      cancelAnimationFrame(focusFrame);
      snapshots.forEach(({ element, inert, inertAttribute, ariaHidden }) => {
        element.inert = inert;
        if (inertAttribute === null) element.removeAttribute("inert");
        else element.setAttribute("inert", inertAttribute);
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      });
      body.style.overflow = previousOverflow;
      body.style.overscrollBehavior = previousOverscrollBehavior;
    };

    return restoreBackground;
  }, [expanded]);

  useEffect(() => {
    if (!expanded || typeof document === "undefined") return;

    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeExpanded();
        return;
      }
      if (event.key !== "Tab") return;

      const container = dialog.current;
      if (!container) return;
      const focusable = getVisibleFocusableElements(container);
      if (focusable.length === 0) {
        event.preventDefault();
        container.focus({ preventScroll: true });
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !container.contains(active)) {
          event.preventDefault();
          last.focus({ preventScroll: true });
        }
      } else if (active === last || !container.contains(active)) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    };

    document.addEventListener("keydown", handler, true);
    return () => document.removeEventListener("keydown", handler, true);
  }, [expanded]);

  useEffect(() => {
    if (expanded) return;
    restoreFocus();
  }, [expanded]);

  useEffect(() => () => restoreFocus(), []);

  const graphFrame = (
    <div ref={frame} className="graph-frame">
      <div className="graph-toolbar">
        <span className="graph-toolbar-heading">
          <Network size={18} aria-hidden="true" />
          <span id={titleId}>{t("graph.frameTitle")}</span>
          <small>
            {t("graph.nodesRelations", {
              nodes: graph.nodes.length,
              relations: graph.edges.length,
            })}
          </small>
        </span>
        <div className="graph-toolbar-actions">
          <button
            type="button"
            className="icon-button"
            aria-label={t("graph.fitView")}
            title={t("graph.fitView")}
            onClick={() =>
              void fitView({
                padding: 0.1,
                duration: prefersReducedMotion ? 0 : 300,
                maxZoom: 1,
              })
            }
          >
            <Scan size={18} aria-hidden="true" />
          </button>
          {expanded && (
            <button
              ref={closeButton}
              type="button"
              className="icon-button graph-close-button"
              aria-label={t("graph.closeExpanded")}
              title={t("graph.closeExpanded")}
              onClick={closeExpanded}
            >
              <X size={18} aria-hidden="true" />
            </button>
          )}
          <button
            ref={expandButton}
            type="button"
            className="icon-button"
            aria-label={expanded ? t("graph.exitExpanded") : t("graph.expand")}
            aria-pressed={expanded}
            title={expanded ? t("graph.exitExpanded") : t("graph.expand")}
            onClick={expanded ? closeExpanded : openExpanded}
          >
            {expanded ? (
              <Minimize2 size={18} aria-hidden="true" />
            ) : (
              <Maximize2 size={18} aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
      <div className="graph-canvas" data-testid="field-graph">
        <ReactFlow<GraphNode>
          colorMode={props.theme}
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.14, maxZoom: 1 }}
          minZoom={0.2}
          maxZoom={1.8}
          zoomOnScroll={expanded}
          zoomActivationKeyCode="Control"
          preventScrolling={expanded}
          ariaLabelConfig={{
            "node.a11yDescription.default": t("graph.nodeDescription"),
            "node.a11yDescription.keyboardDisabled": t(
              "graph.nodeDescriptionKeyboardDisabled",
            ),
            "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }) =>
              t("graph.nodeLiveMessage", {
                direction: directionLabels[direction] ?? direction,
                x,
                y,
              }),
            "edge.a11yDescription.default": t("graph.edgeDescription"),
            "controls.ariaLabel": t("graph.controls"),
            "controls.zoomIn.ariaLabel": t("graph.zoomIn"),
            "controls.zoomOut.ariaLabel": t("graph.zoomOut"),
            "controls.fitView.ariaLabel": t("graph.controlsFitView"),
            "controls.interactive.ariaLabel": t("graph.interactive"),
            "minimap.ariaLabel": t("graph.minimap"),
          }}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          elementsSelectable={false}
        >
          <Background
            variant={BackgroundVariant.Dots}
            color="var(--graph-grid)"
            gap={20}
            size={1}
          />
          <Controls showInteractive={false} />
        </ReactFlow>
        <div
          className="graph-legend"
          role="group"
          aria-label={t("graph.legend")}
        >
          <span>
            <i className="graph-legend-swatch prerequisite" />
            {t("graph.rolePrerequisite")}
          </span>
          <span>
            <i className="graph-legend-swatch current" />
            {t("graph.roleCurrent")}
          </span>
          <span>
            <i className="graph-legend-swatch subfield" />
            {t("graph.roleSubfield")}
          </span>
        </div>
      </div>
      <div className="graph-footer" id={descriptionId}>
        <span>
          {expanded ? t("graph.helpExpanded") : t("graph.helpCompact")}
        </span>
        <span>
          {props.maxRelations === 0
            ? t("graph.fullView")
            : t("graph.overviewLimit", { count: props.maxRelations ?? 3 })}
        </span>
      </div>
    </div>
  );

  if (!expanded || typeof document === "undefined") return graphFrame;

  return createPortal(
    <div
      className="field-graph-modal-backdrop"
      data-field-graph-dialog="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeExpanded();
      }}
    >
      <div
        ref={dialog}
        className="field-graph-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        {graphFrame}
      </div>
    </div>,
    document.body,
  );
}
export function FieldGraph(props: Props) {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  );
}
