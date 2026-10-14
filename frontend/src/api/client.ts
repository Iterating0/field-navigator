import type { ExploreEvent, FieldNode, Mode, QueryResolution } from "../types";

export async function resolveQuery(
  query: string,
  mode: Mode,
  signal?: AbortSignal,
): Promise<QueryResolution> {
  const response = await fetch("/api/fields/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode }),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(40_000)])
      : AbortSignal.timeout(40_000),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : "暂时无法识别研究方向，请重试或使用明确的领域名称。",
    );
  if (
    !body ||
    !["ready", "choose", "clarify"].includes(body.status) ||
    !["llm", "alias", "direct"].includes(body.source) ||
    !Array.isArray(body.candidates) ||
    body.candidates.length > 3 ||
    body.candidates.some(
      (candidate: QueryResolution["candidates"][number]) =>
        !candidate ||
        typeof candidate.query !== "string" ||
        candidate.query.length > 180 ||
        typeof candidate.name !== "string" ||
        !Array.isArray(candidate.evidence_papers),
    )
  )
    throw new Error("研究方向数据不完整，请重试。");
  return body as QueryResolution;
}

export async function exploreField(
  query: string,
  mode: Mode,
  refresh = false,
  onEvent?: (event: ExploreEvent) => void,
  signal?: AbortSignal,
  researchQuestion?: string,
): Promise<FieldNode> {
  const response = await fetch("/api/fields/explore/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      mode,
      refresh,
      ...(researchQuestion?.trim()
        ? { research_question: researchQuestion.trim() }
        : {}),
    }),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(280_000)])
      : AbortSignal.timeout(280_000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : "请求失败，请检查后端是否已启动。",
    );
  }
  if (!response.body) throw new Error("浏览器未提供流式响应，请更新浏览器。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: FieldNode | undefined;
  function consume(line: string) {
    if (!line.trim()) return;
    const event: ExploreEvent = JSON.parse(line);
    if (event.type === "error") throw new Error(event.detail);
    if (event.type === "partial" || event.type === "complete") {
      if (
        !event.field ||
        typeof event.field.name !== "string" ||
        !Array.isArray(event.field.core_papers)
      )
        throw new Error("后端返回了无效的领域数据，请检查服务日志。");
    }
    if (event.type === "complete") result = event.field;
    onEvent?.(event);
  }
  try {
    while (!result) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) consume(line);
      if (done) {
        consume(buffer);
        break;
      }
    }
    if (!result) throw new Error("连接中断，分析未完成。请重试。");
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
