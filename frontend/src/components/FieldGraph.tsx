import { useEffect, useMemo, useRef, useState } from "react";
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
} from "lucide-react";
import type { FieldNode } from "../types";
import { normalizeField as keyOf } from "../state/exploration";
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
  return (
    <div className={`field-node ${data.role}`}>
      <Handle type="target" position={Position.Left} />
      <span className="node-eyebrow">
        {data.role === "current" ? (
          <Compass size={13} />
        ) : (
          <span className="node-dot" />
        )}
        {data.role === "current"
          ? "正在探索"
          : data.role === "prerequisite"
            ? "前置领域"
            : "研究分支"}
      </span>
      <strong title={data.name}>{data.name}</strong>
      <div className="node-bottom">
        <span>
          {data.analyzed ? (
            <>
              <Check size={11} /> {data.paperCount} 篇论文
            </>
          ) : (
            "点击继续探索"
          )}
        </span>
        <button
          className="node-action nodrag"
          aria-label={`探索 ${data.name}`}
          disabled={data.busy || data.role === "current"}
          onClick={(e) => {
            e.stopPropagation();
            data.onExplore(data.name);
          }}
        >
          <ArrowUpRight size={15} />
        </button>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
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
      ariaLabel: `${name}，${role === "current" ? "当前领域" : "可探索领域"}`,
    });
  }
  function edge(from: string, to: string, pre: boolean) {
    const stroke =
      theme === "dark"
        ? pre
          ? "#65bda6"
          : "#a59add"
        : pre
          ? "#427e6e"
          : "#7970ad";
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
        (i - (relations.length - 1) / 2) * 116,
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
            (row++ - (second.length - 1) / 2) * 138,
          );
        if (kind === "prerequisite") edge(child, parent, true);
        else edge(parent, child, false);
      });
    }
  }
  return { nodes, edges };
}
function GraphCanvas(props: Props) {
  const { fitView } = useReactFlow();
  const [expanded, setExpanded] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(
        () => void fitView({ padding: 0.1, duration: 250, maxZoom: 1 }),
        100,
      );
    });
    if (frame.current) observer.observe(frame.current);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
  }, [fitView]);
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
  const layoutKey = graph.nodes.map((n) => n.id).join("|") + props.field.id;
  useEffect(() => {
    const timer = setTimeout(
      () => void fitView({ padding: 0.1, duration: 350, maxZoom: 1 }),
      50,
    );
    return () => clearTimeout(timer);
  }, [layoutKey, fitView, expanded]);
  useEffect(() => {
    if (!expanded) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [expanded]);
  return (
    <div
      ref={frame}
      className={`graph-frame ${expanded ? "graph-expanded" : ""}`}
    >
      <div className="graph-toolbar">
        <span>
          <Network size={15} />
          领域关系图
          <small>
            {graph.nodes.length} 个节点 · {graph.edges.length} 条关系
          </small>
        </span>
        <div>
          <button
            className="icon-button"
            aria-label="适应画布"
            onClick={() =>
              void fitView({ padding: 0.1, duration: 300, maxZoom: 1 })
            }
          >
            <Scan size={16} />
          </button>
          <button
            className="icon-button"
            aria-label={expanded ? "退出放大图谱" : "放大图谱"}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
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
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          onNodeClick={(_, node) => {
            if (!props.busy && node.id !== keyOf(props.field.name))
              props.onExplore(node.data.name);
          }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            color="var(--graph-grid)"
            gap={20}
            size={1}
          />
          <Controls showInteractive={false} />
        </ReactFlow>
        <div className="graph-legend">
          <span>
            <i className="teal" />
            前置领域
          </span>
          <span>
            <i className="blue" />
            当前领域
          </span>
          <span>
            <i className="violet" />
            研究分支
          </span>
        </div>
      </div>
      <div className="graph-footer">
        <span>
          {expanded
            ? "滚轮缩放 · 拖动画布 · 点击节点深入探索"
            : "滚轮滚动页面 · Ctrl + 滚轮缩放 · 拖动画布"}
        </span>
        <span>
          {props.maxRelations === 0
            ? "完整关系视图"
            : `概览 · 每侧最多 ${props.maxRelations ?? 3} 个方向`}
        </span>
      </div>
    </div>
  );
}
export function FieldGraph(props: Props) {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  );
}
