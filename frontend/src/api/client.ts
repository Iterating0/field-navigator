import type { ExploreEvent, FieldNode, Mode } from "../types";
export async function exploreField(
  query: string,
  mode: Mode,
  refresh = false,
  onEvent?: (event: ExploreEvent) => void,
  signal?: AbortSignal,
): Promise<FieldNode> {
  const response = await fetch("/api/fields/explore/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, refresh }),
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
