import type { Language, Paper } from "../types/index.ts";

export function abstractProvenanceLabel(
  paper: Paper,
  language: Language = "zh-CN",
): string {
  const prefix = language === "en" ? "Abstract source: " : "摘要来源：";
  try {
    const record = new URL(paper.abstract_source_record_id ?? "");
    if (
      record.hostname === "api.datacite.org" &&
      record.pathname.startsWith("/dois/")
    )
      return `${prefix}${language === "en" ? "DataCite registered metadata" : "DataCite 注册元数据"}`;
    if (record.hostname === "arxiv.org" && record.pathname.startsWith("/abs/"))
      return `${prefix}${language === "en" ? "arXiv metadata" : "arXiv 元数据"}`;
  } catch {
    // An index alias can identify a version without being a URL.
  }
  return language === "en"
    ? "Abstract metadata comes from an independent source or version"
    : "摘要元数据来自独立来源或版本";
}
