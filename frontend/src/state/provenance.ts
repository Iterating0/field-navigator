import type { Paper } from "../types";

export function abstractProvenanceLabel(paper: Paper): string {
  try {
    const record = new URL(paper.abstract_source_record_id ?? "");
    if (record.hostname === "api.datacite.org" && record.pathname.startsWith("/dois/"))
      return "摘要来源：DataCite 注册元数据";
    if (record.hostname === "arxiv.org" && record.pathname.startsWith("/abs/"))
      return "摘要来源：arXiv 元数据";
  } catch {
    // An index alias can identify a version without being a URL.
  }
  return "摘要元数据来自独立来源或版本";
}
