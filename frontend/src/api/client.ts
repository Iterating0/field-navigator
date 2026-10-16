import {
  normalizeLanguage,
  type ExploreEvent,
  type FieldNode,
  type Language,
  type Mode,
  type QueryResolution,
} from "../types/index.ts";

function languageMismatchMessage(language: Language): string {
  return language === "en"
    ? "The server returned a different language than requested. Restart or update the service, then try again."
    : "后端返回的结果语言与当前请求不一致，请重启或更新服务后重试。";
}

function fallbackMessage(
  language: Language,
  kind: "resolve" | "explore" | "stream" | "invalid",
): string {
  if (language === "en") {
    if (kind === "resolve")
      return "The research direction could not be identified. Try again or use a specific field name.";
    if (kind === "explore")
      return "The request failed. Check that the backend service is running.";
    if (kind === "stream")
      return "The analysis connection ended before a complete result. Please try again.";
    return "The server returned incomplete research-direction data. Please try again.";
  }
  if (kind === "resolve")
    return "暂时无法识别研究方向，请重试或使用明确的领域名称。";
  if (kind === "explore") return "请求失败，请检查后端是否已启动。";
  if (kind === "stream") return "连接中断，分析未完成。请重试。";
  return "研究方向数据不完整，请重试。";
}

function responseLanguage(value: unknown): Language | null {
  // A missing marker means a legacy Chinese backend, never the requested
  // language. This prevents an old Chinese response from being labelled and
  // cached as English.
  if (value === undefined) return "zh-CN";
  if (value === "zh-CN" || value === "en") return value;
  return null;
}

function requireResponseLanguage(
  value: unknown,
  requested: Language,
): Language {
  const actual = responseLanguage(value);
  if (actual !== requested) throw new Error(languageMismatchMessage(requested));
  return actual;
}

export async function resolveQuery(
  query: string,
  mode: Mode,
  signal?: AbortSignal,
  language: Language = "zh-CN",
): Promise<QueryResolution> {
  const requestLanguage = normalizeLanguage(language);
  const response = await fetch("/api/fields/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, language: requestLanguage }),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(40_000)])
      : AbortSignal.timeout(40_000),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : fallbackMessage(requestLanguage, "resolve"),
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
    throw new Error(fallbackMessage(requestLanguage, "invalid"));
  const actualLanguage = requireResponseLanguage(
    body.language,
    requestLanguage,
  );
  return {
    ...(body as QueryResolution),
    language: actualLanguage,
  };
}

export async function exploreField(
  query: string,
  mode: Mode,
  refresh = false,
  onEvent?: (event: ExploreEvent) => void,
  signal?: AbortSignal,
  researchQuestion?: string,
  language: Language = "zh-CN",
): Promise<FieldNode> {
  const requestLanguage = normalizeLanguage(language);
  const response = await fetch("/api/fields/explore/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      mode,
      refresh,
      language: requestLanguage,
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
        : fallbackMessage(requestLanguage, "explore"),
    );
  }
  if (!response.body)
    throw new Error(
      requestLanguage === "en"
        ? "The browser did not provide a streaming response. Please update the browser."
        : "浏览器未提供流式响应，请更新浏览器。",
    );
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: FieldNode | undefined;
  function consume(line: string) {
    if (!line.trim()) return;
    let event: ExploreEvent;
    try {
      event = JSON.parse(line) as ExploreEvent;
    } catch {
      throw new Error(fallbackMessage(requestLanguage, "invalid"));
    }
    if (event.type === "error") throw new Error(event.detail);
    if (event.type === "partial" || event.type === "complete") {
      if (
        !event.field ||
        typeof event.field.name !== "string" ||
        !Array.isArray(event.field.core_papers)
      )
        throw new Error(fallbackMessage(requestLanguage, "invalid"));
      const actualLanguage = requireResponseLanguage(
        event.field.language,
        requestLanguage,
      );
      event = {
        ...event,
        field: { ...event.field, language: actualLanguage },
      };
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
    if (!result) throw new Error(fallbackMessage(requestLanguage, "stream"));
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
