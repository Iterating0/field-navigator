"""Run a serial, evidence-backed recommendation benchmark.

The evaluator deliberately keeps raw candidate metadata and model traffic in
``.runtime/recommendation-eval``.  The public fixture contains only questions,
branch targets and bibliographic anchors.  Use the project's backend virtual
environment, for example::

    backend/.venv/Scripts/python.exe scripts/evaluate_recommendations.py \
        --output .runtime/recommendation-eval --label baseline \
        --backend-root .runtime/recommendation-eval/baseline-source

``--replay`` is an offline, rank-only replay.  It reuses a prior run's
candidate pool and paper judgments, imports only the selected backend's
current ``PaperRanker``, and never calls ``FieldExplorer``, an LLM, or a
network provider.  The recorded map is preserved with an explicit
``map_revalidated: false`` annotation; the row status is ``ranking_replay``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import unicodedata
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "evaluation" / "cases.json"
RUNTIME_ROOT = REPO_ROOT / ".runtime" / "recommendation-eval"
DEFAULT_BACKEND_ROOT = REPO_ROOT / "backend"
CASE_TIMEOUT_SECONDS = 240.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def jsonable(value: Any) -> Any:
    """Convert provider/model values to JSON without exposing settings."""
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def error_record(exc: BaseException) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc)[:1000],
    }
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        result["status_code"] = status_code
    return result


def resolve_path(value: str | Path, *, base: Path = REPO_ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def output_file(value: str, label: str) -> Path:
    path = resolve_path(value)
    if path.suffix.lower() == ".json":
        return path
    return path / f"{label}.json"


def runtime_only(path: Path) -> bool:
    try:
        path.resolve().relative_to((REPO_ROOT / ".runtime").resolve())
        return True
    except ValueError:
        return False


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "run"


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)).strip()


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip().casefold()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value.rstrip(" .")


def normalize_arxiv(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip().casefold()
    value = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", value)
    return value.removesuffix(".pdf")


def paper_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return jsonable(value)
    return {"value": jsonable(value)}


def paper_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [paper_dict(item) for item in value]
    return [paper_dict(value)]


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    source_cases = raw.get("cases")
    if source_cases is None:
        source_cases = raw.get("questions", [])
    cases: list[dict[str, Any]] = []
    for source in source_cases:
        case_id = source.get("id") or slug(source.get("title", "case"))
        query = source.get("canonical_query")
        if not query:
            query_by_id = {
                "ktao3-interface-superconductivity": "KTaO3 interface superconductivity",
                "one-dimensional-nhse": "non-Hermitian skin effect bulk boundary correspondence",
                "magic-angle-tbg-superconductivity": "magic angle twisted bilayer graphene superconductivity",
            }
            query = query_by_id.get(case_id, source.get("title", case_id))
        branches = source.get("target_branches")
        if branches is None:
            branches = [
                {"id": slug(item.get("name", "branch")), "label": item.get("name", "branch")}
                for item in source.get("branches", [])
            ]
        anchors = source.get("anchors")
        if anchors is None:
            anchors = []
            for index, item in enumerate(source.get("core_papers", []), start=1):
                links = item.get("primary_links", [])
                anchors.append({
                    "id": item.get("id", f"{case_id}-anchor-{index}"),
                    "title": item.get("title", ""),
                    "year": item.get("year"),
                    "doi": item.get("doi"),
                    "arxiv_id": item.get("arxiv") or item.get("arxiv_id"),
                    "primary_source_url": links[0] if links else item.get("primary_source_url"),
                    "branch_ids": [],
                })
        cases.append({
            "id": case_id,
            "canonical_query": query,
            "research_question": source.get("research_question", source.get("scope", source.get("title", query))),
            "target_branches": branches,
            "anchors": anchors,
        })
    return cases


def import_backend(backend_root: Path, *, include_explorer: bool = True) -> SimpleNamespace:
    """Import a selected backend tree before importing any ``app`` module."""
    backend_root = backend_root.resolve()
    if not (backend_root / "app").is_dir():
        raise SystemExit(f"backend root does not contain app/: {backend_root}")
    sys.path.insert(0, str(backend_root))
    # Imports are intentionally local so --backend-root can freeze an old
    # source snapshot for baseline evaluation after production edits.
    from app.config import Settings
    from app.db.cache import FieldCache
    from app.models.schemas import FieldNode, Paper, PaperJudgment
    from app.providers.llm import CompatibleLLMProvider
    from app.providers.mock import MockLLMProvider
    from app.providers.openalex import OpenAlexProvider
    from app.services.field_decomposer import FieldDecomposer
    from app.services.paper_ranker import PaperRanker

    field_explorer = None
    if include_explorer:
        from app.services.field_explorer import FieldExplorer
        field_explorer = FieldExplorer

    return SimpleNamespace(
        Settings=Settings,
        FieldCache=FieldCache,
        FieldNode=FieldNode,
        Paper=Paper,
        PaperJudgment=PaperJudgment,
        CompatibleLLMProvider=CompatibleLLMProvider,
        MockLLMProvider=MockLLMProvider,
        OpenAlexProvider=OpenAlexProvider,
        FieldDecomposer=FieldDecomposer,
        FieldExplorer=field_explorer,
        PaperRanker=PaperRanker,
    )


class RecordingPaperProvider:
    """Record every paper-provider call, including optional retriever calls."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        entry: dict[str, Any] = {
            "index": len(self.calls),
            "method": method,
            "input": {"args": jsonable(args), "kwargs": jsonable(kwargs)},
            "started_at": utc_now(),
        }
        try:
            result = await getattr(self.inner, method)(*args, **kwargs)
            entry["output"] = paper_list(result)
            return result
        except BaseException as exc:
            entry["error"] = error_record(exc)
            raise
        finally:
            entry["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            entry["finished_at"] = utc_now()
            self.calls.append(entry)

    async def search_papers(self, query: str, limit: int = 40, **kwargs: Any) -> list[Any]:
        return await self._call("search_papers", query, limit, **kwargs)

    async def get_paper(self, paper_id: str, **kwargs: Any) -> Any:
        return await self._call("get_paper", paper_id, **kwargs)

    async def get_citations(self, paper_id: str, limit: int = 40, **kwargs: Any) -> list[Any]:
        return await self._call("get_citations", paper_id, limit, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Keep optional retriever/provider methods observable as well."""
        target = getattr(self.inner, name)
        if not callable(target):
            return target

        async def recorded(*args: Any, **kwargs: Any) -> Any:
            return await self._call(name, *args, **kwargs)

        return recorded


class RecordingLLMProvider:
    """Record actual structured prompts/responses without recording credentials."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        entry: dict[str, Any] = {
            "index": len(self.calls),
            "method": method,
            "input": {"args": jsonable(args), "kwargs": jsonable(kwargs)},
            "started_at": utc_now(),
        }
        try:
            result = getattr(self.inner, method)(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            entry["output"] = jsonable(result)
            return result
        except BaseException as exc:
            entry["error"] = error_record(exc)
            raise
        finally:
            entry["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            entry["finished_at"] = utc_now()
            self.calls.append(entry)

    async def generate_structured(self, **kwargs: Any) -> Any:
        return await self._call("generate_structured", **kwargs)

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        if not callable(target):
            return target

        async def recorded(*args: Any, **kwargs: Any) -> Any:
            return await self._call(name, *args, **kwargs)

        return recorded


class RecordingRetriever:
    """Record optional retrieval planning and the merged paper result."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _papers_from_result(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, dict):
            value = result.get("papers")
        else:
            value = getattr(result, "papers", None)
        return paper_list(value) if value is not None else []

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        entry: dict[str, Any] = {
            "index": len(self.calls),
            "method": method,
            "input": {"args": jsonable(args), "kwargs": jsonable(kwargs)},
            "started_at": utc_now(),
        }
        try:
            result = getattr(self.inner, method)(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            entry["output"] = jsonable(result)
            papers = self._papers_from_result(result)
            if papers:
                entry["result_papers"] = papers
            queries = result.get("queries") if isinstance(result, dict) else getattr(result, "queries", None)
            warnings = result.get("warnings") if isinstance(result, dict) else getattr(result, "warnings", None)
            if queries is not None:
                entry["queries"] = jsonable(queries)
            if warnings is not None:
                entry["warnings"] = jsonable(warnings)
            return result
        except BaseException as exc:
            entry["error"] = error_record(exc)
            raise
        finally:
            entry["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            entry["finished_at"] = utc_now()
            self.calls.append(entry)

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        if not callable(target):
            return target

        async def recorded(*args: Any, **kwargs: Any) -> Any:
            return await self._call(name, *args, **kwargs)

        return recorded


class ReplayPaperProvider:
    def __init__(self, case_record: dict[str, Any], paper_model: Any):
        self.paper_model = paper_model
        self.search_results: list[list[dict[str, Any]]] = []
        for call in case_record.get("paper_calls", []):
            if call.get("method") == "search_papers" and isinstance(call.get("output"), list):
                self.search_results.append(call["output"])
        if not self.search_results and case_record.get("candidate_pool"):
            self.search_results.append(case_record["candidate_pool"])
        self.index = 0

    async def search_papers(self, query: str, limit: int = 40, **kwargs: Any) -> list[Any]:
        if self.index >= len(self.search_results):
            raise RuntimeError("replay has no recorded search_papers response")
        raw = self.search_results[self.index]
        self.index += 1
        return [self.paper_model.model_validate(item) for item in raw]

    async def get_paper(self, paper_id: str, **kwargs: Any) -> Any:
        raise RuntimeError("replay has no recorded get_paper response")

    async def get_citations(self, paper_id: str, limit: int = 40, **kwargs: Any) -> list[Any]:
        raise RuntimeError("replay has no recorded get_citations response")


class ReplayLLMProvider:
    def __init__(self, case_record: dict[str, Any]):
        self.calls = [item for item in case_record.get("llm_calls", []) if "output" in item]
        self.used: set[int] = set()

    @staticmethod
    def _role(item: dict[str, Any]) -> str:
        system = (((item.get("input") or {}).get("kwargs") or {}).get("system") or "")
        if "ONLY builds the field map" in system:
            return "map"
        if "ONLY assesses papers" in system:
            return "papers"
        return ""

    async def generate_structured(self, **kwargs: Any) -> Any:
        requested_role = self._role({"input": {"kwargs": kwargs}})
        index = next(
            (index for index, item in enumerate(self.calls)
             if index not in self.used and (not requested_role or self._role(item) == requested_role)),
            None,
        )
        if index is None:
            raise RuntimeError("replay has no recorded generate_structured response")
        self.used.add(index)
        item = self.calls[index]
        return item["output"]

    def __getattr__(self, name: str) -> Any:
        async def missing(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"replay has no recorded LLM method: {name}")

        return missing


def discover_retriever(module: SimpleNamespace, settings: Any, client: Any,
                       papers: Any, llm: Any) -> tuple[Any | None, dict[str, Any]]:
    """Instantiate a future optional LiteratureRetriever when its constructor is visible."""
    explorer_parameters = inspect.signature(module.FieldExplorer.__init__).parameters
    if "retriever" not in explorer_parameters:
        return None, {"field_parameter": False, "class_found": False, "enabled": False}

    candidates = [
        ("app.services.literature_retriever", "LiteratureRetriever"),
        ("app.services.retriever", "LiteratureRetriever"),
        ("app.providers.literature_retriever", "LiteratureRetriever"),
        ("app.services.field_explorer", "LiteratureRetriever"),
    ]
    errors: list[str] = []
    for module_name, class_name in candidates:
        try:
            cls = getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{module_name}: {type(exc).__name__}")
            continue
        try:
            signature = inspect.signature(cls)
            values = {
                "settings": settings,
                "client": client,
                "http": client,
                "http_client": client,
                "papers": papers,
                "paper_provider": papers,
                "provider": papers,
                "llm": llm,
                "llm_provider": llm,
            }
            kwargs = {
                name: values[name]
                for name, parameter in signature.parameters.items()
                if name in values and parameter.kind in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)
            }
            required = [
                name for name, parameter in signature.parameters.items()
                if name != "self"
                and parameter.default is parameter.empty
                and parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)
            ]
            if any(name not in kwargs for name in required):
                errors.append(f"{module_name}: unsupported required constructor args {required}")
                continue
            instance = cls(**kwargs)
            return instance, {
                "field_parameter": True,
                "class_found": True,
                "enabled": True,
                "class": f"{module_name}.{class_name}",
                "metadata_verification_enabled": bool(getattr(instance, "metadata_verifier", None)),
            }
        except Exception as exc:  # optional extension must not block the legacy run
            errors.append(f"{module_name}: {type(exc).__name__}: {str(exc)[:160]}")
    return None, {
        "field_parameter": True,
        "class_found": False,
        "enabled": False,
        "errors": errors,
    }


def build_stack(module: SimpleNamespace, settings: Any, client: Any,
                replay_record: dict[str, Any] | None) -> tuple[Any, RecordingPaperProvider, RecordingLLMProvider,
                                                               RecordingRetriever | None, dict[str, Any]]:
    if replay_record is None:
        llm_inner = (
            module.CompatibleLLMProvider(client, settings)
            if settings.llm_api_key
            else module.MockLLMProvider()
        )
        paper_inner = module.OpenAlexProvider(
            client, settings.openalex_api_key, settings.openalex_mailto
        )
    else:
        llm_inner = ReplayLLMProvider(replay_record)
        paper_inner = ReplayPaperProvider(replay_record, module.Paper)
    llm = RecordingLLMProvider(llm_inner)
    papers = RecordingPaperProvider(paper_inner)
    decomposer = module.FieldDecomposer(llm, require_evidence=bool(settings.llm_api_key))
    cache = module.FieldCache(settings.db_path)
    retriever, retriever_info = discover_retriever(module, settings, client, papers, llm)
    recording_retriever = RecordingRetriever(retriever) if retriever is not None else None
    kwargs = {
        "settings": settings,
        "papers": papers,
        "decomposer": decomposer,
        "ranker": module.PaperRanker(settings.rank_weights),
        "cache": cache,
    }
    explorer_parameters = inspect.signature(module.FieldExplorer.__init__).parameters
    if "retriever" in explorer_parameters:
        parameter = explorer_parameters["retriever"]
        # Passing None is useful for a future required-but-unavailable
        # extension: the run then records the constructor/runtime error rather
        # than silently falling back to a different production graph.
        if recording_retriever is not None or parameter.default is parameter.empty:
            kwargs["retriever"] = recording_retriever
    explorer = module.FieldExplorer(**kwargs)
    return explorer, papers, llm, recording_retriever, retriever_info


def candidate_metrics(case: dict[str, Any], candidates: list[dict[str, Any]], node: Any | None) -> dict[str, Any]:
    anchors = case.get("anchors", [])
    doi_counts = Counter(normalize_doi(item.get("doi")) for item in candidates if normalize_doi(item.get("doi")))
    title_counts = Counter(normalize_title(item.get("title")) for item in candidates if normalize_title(item.get("title")))
    id_counts = Counter(str(item.get("id", "")) for item in candidates if item.get("id"))
    candidate_by_doi: dict[str, list[int]] = {}
    candidate_by_title: dict[str, list[int]] = {}
    for index, item in enumerate(candidates):
        doi = normalize_doi(item.get("doi"))
        title = normalize_title(item.get("title"))
        if doi:
            candidate_by_doi.setdefault(doi, []).append(index)
        if title:
            candidate_by_title.setdefault(title, []).append(index)
    matches = []
    for anchor in anchors:
        doi = normalize_doi(anchor.get("doi"))
        title = normalize_title(anchor.get("title"))
        indices = candidate_by_doi.get(doi, []) if doi else []
        match_type = "doi" if indices else ""
        if not indices and title:
            indices = candidate_by_title.get(title, [])
            match_type = "title" if indices else ""
        matches.append({
            "anchor_id": anchor.get("id"),
            "title": anchor.get("title"),
            "candidate_indices": indices,
            "match_type": match_type or None,
            "found": bool(indices),
        })
    found = sum(1 for item in matches if item["found"])
    core: list[dict[str, Any]] = []
    if node is not None:
        core = [paper_dict(item.paper) for item in node.core_papers]
    core_dois = {normalize_doi(item.get("doi")) for item in core if normalize_doi(item.get("doi"))}
    core_titles = {normalize_title(item.get("title")) for item in core if normalize_title(item.get("title"))}
    top8_matches = [
        item for item in anchors
        if (normalize_doi(item.get("doi")) and normalize_doi(item.get("doi")) in core_dois)
        or (normalize_title(item.get("title")) and normalize_title(item.get("title")) in core_titles)
    ]
    # OpenAlex calls this work_type.  Older Paper payloads do not retain it;
    # keep that absence explicit instead of guessing a document type.
    type_values = [item.get("work_type") or item.get("type") for item in candidates]
    type_counts = Counter(str(value) for value in type_values if value)
    source_counts = Counter(str(item.get("source", "unknown")) for item in candidates)
    return {
        "anchor_count": len(anchors),
        "candidate_found_count": found,
        "candidate_recall": round(found / len(anchors), 4) if anchors else None,
        "matches": matches,
        "top8_hit_count": len(top8_matches),
        "top8_hit": bool(top8_matches),
        "top8_anchor_ids": [item.get("id") for item in top8_matches],
        "duplicates": {
            "by_id": sum(max(count - 1, 0) for count in id_counts.values()),
            "by_doi": sum(max(count - 1, 0) for count in doi_counts.values()),
            "by_title": sum(max(count - 1, 0) for count in title_counts.values()),
        },
        "types": {
            "field_available": bool(type_counts),
            "distribution": dict(type_counts) if type_counts else {"unknown": len(candidates)},
            "source_distribution": dict(source_counts),
        },
        "candidate_count": len(candidates),
        "core_count": len(core),
    }


def replay_index(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("case_id")): item for item in raw.get("cases", []) if item.get("case_id")}


def _year(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _metadata_matches(alias: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Match a compact LLM paper alias to recorded provider metadata.

    The old decomposer sent compact ``p1``... aliases with title/year (and
    newer payloads may also carry DOI).  DOI is authoritative when both sides
    have it; otherwise title plus year is used.  A title-only alias is allowed
    only when no year was supplied by the recorded payload.
    """
    alias_doi = normalize_doi(alias.get("doi"))
    candidate_doi = normalize_doi(candidate.get("doi"))
    if alias_doi and candidate_doi:
        return alias_doi == candidate_doi
    alias_title = normalize_title(alias.get("title"))
    candidate_title = normalize_title(candidate.get("title"))
    if not alias_title or alias_title != candidate_title:
        return False
    alias_year = _year(alias.get("year"))
    return alias_year is None or alias_year == _year(candidate.get("year"))


def _recorded_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = record.get("candidate_pool")
    if isinstance(candidates, list) and candidates:
        return [paper_dict(item) for item in candidates]
    for call in record.get("paper_calls", []):
        if call.get("method") == "search_papers" and isinstance(call.get("output"), list):
            return [paper_dict(item) for item in call["output"]]
    return []


def _recorded_alias_payload(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    aliases: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    for call in record.get("llm_calls", []):
        payload = ((call.get("input") or {}).get("kwargs") or {}).get("payload") or {}
        papers = payload.get("papers") if isinstance(payload, dict) else None
        if not aliases and isinstance(papers, list):
            aliases = [paper_dict(item) for item in papers]
        output = call.get("output")
        output_judgments = output.get("paper_judgments") if isinstance(output, dict) else None
        if not judgments and isinstance(output_judgments, list):
            judgments = [paper_dict(item) for item in output_judgments]
    return aliases, judgments


def _map_recorded_aliases(
    aliases: list[dict[str, Any]], candidates: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, Any]]:
    """Map compact aliases without silently assigning an ambiguous paper."""
    alias_map: dict[str, int] = {}
    limits: list[str] = []
    mapping: list[dict[str, Any]] = []
    if not aliases:
        return alias_map, {
            "method": "none",
            "alias_count": 0,
            "candidate_count": len(candidates),
            "matched_count": 0,
            "unmatched_aliases": [],
            "ambiguous_aliases": [],
            "limits": ["recorded LLM input contained no paper metadata"],
            "mapping": mapping,
        }

    # The compact payload is produced from the candidate list in order.  Use
    # that fact only after verifying every metadata tuple; this handles exact
    # duplicate titles safely while still refusing a shifted/malformed list.
    ordered = len(aliases) == len(candidates) and all(
        _metadata_matches(alias, candidate)
        for alias, candidate in zip(aliases, candidates)
    )
    unmatched: list[str] = []
    ambiguous: list[str] = []
    if ordered:
        for index, alias in enumerate(aliases):
            alias_id = str(alias.get("id") or f"p{index + 1}")
            alias_map[alias_id] = index
            mapping.append({
                "alias": alias_id,
                "candidate_index": index,
                "candidate_id": candidates[index].get("id"),
                "method": "ordered_metadata_verified",
            })
        method = "ordered_metadata_verified"
    else:
        method = "unique_metadata"
        if len(aliases) != len(candidates):
            limits.append(
                f"candidate/LLM metadata count differs ({len(candidates)} candidates vs {len(aliases)} aliases)"
            )
        used: set[int] = set()
        for alias in aliases:
            alias_id = str(alias.get("id") or f"p{len(mapping) + 1}")
            matches = [
                index for index, candidate in enumerate(candidates)
                if index not in used and _metadata_matches(alias, candidate)
            ]
            if len(matches) == 1:
                index = matches[0]
                used.add(index)
                alias_map[alias_id] = index
                mapping.append({
                    "alias": alias_id,
                    "candidate_index": index,
                    "candidate_id": candidates[index].get("id"),
                    "method": "unique_metadata",
                })
            elif not matches:
                unmatched.append(alias_id)
            else:
                ambiguous.append(alias_id)
        if unmatched:
            limits.append(f"unmatched compact aliases: {', '.join(unmatched[:12])}")
        if ambiguous:
            limits.append(f"ambiguous compact aliases: {', '.join(ambiguous[:12])}")
    if len(alias_map) != len(aliases):
        limits.append(f"mapped only {len(alias_map)}/{len(aliases)} recorded aliases")
    return alias_map, {
        "method": method,
        "alias_count": len(aliases),
        "candidate_count": len(candidates),
        "matched_count": len(alias_map),
        "unmatched_aliases": unmatched,
        "ambiguous_aliases": ambiguous,
        "limits": limits,
        "mapping": mapping,
    }


def _replay_judgments(
    module: SimpleNamespace, raw_judgments: list[dict[str, Any]],
    aliases: list[dict[str, Any]], candidates: list[dict[str, Any]],
    alias_map: dict[str, int], mapping_info: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    limits = list(mapping_info.get("limits", []))
    if not raw_judgments:
        return [], {
            "mode": "heuristic_no_recorded_judgments",
            "recorded_count": 0,
            "mapped_count": 0,
            "limits": limits + ["recorded run had no paper_judgments output"],
        }

    mapped: list[Any] = []
    unresolved: list[str] = []
    invalid: list[str] = []
    for item in raw_judgments:
        alias_id = str(item.get("paper_id", ""))
        index = alias_map.get(alias_id)
        if index is None:
            # Newer runs may already record a provider ID rather than pN.
            index = next(
                (candidate_index for candidate_index, candidate in enumerate(candidates)
                 if str(candidate.get("id")) == alias_id),
                None,
            )
        if index is None or index >= len(candidates):
            unresolved.append(alias_id or "<missing-paper-id>")
            continue
        payload = dict(item)
        payload["paper_id"] = str(candidates[index].get("id"))
        try:
            mapped.append(module.PaperJudgment.model_validate(payload))
        except Exception:
            invalid.append(alias_id or "<missing-paper-id>")
    if unresolved:
        limits.append(f"unmatched judgment aliases: {', '.join(unresolved[:12])}")
    if invalid:
        limits.append(f"invalid recorded judgments: {', '.join(invalid[:12])}")
    complete = (
        len(raw_judgments) == len(candidates)
        and len(mapped) == len(raw_judgments)
        and mapping_info.get("matched_count") == len(aliases) == len(candidates)
    )
    if not complete:
        limits.append(
            f"judgment metadata incomplete ({len(mapped)}/{len(candidates)}); using heuristic ranking"
        )
        return [], {
            "mode": "heuristic_incomplete_recorded_judgments",
            "recorded_count": len(raw_judgments),
            "mapped_count": len(mapped),
            "limits": limits,
        }
    return mapped, {
        "mode": "recorded_judgments",
        "recorded_count": len(raw_judgments),
        "mapped_count": len(mapped),
        "limits": limits,
    }


def run_ranking_replay(
    module: SimpleNamespace, settings: Any, case: dict[str, Any],
    replay_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Replay only ranking from recorded candidates/judgments, without I/O."""
    started = time.perf_counter()
    row: dict[str, Any] = {
        "case_id": case["id"],
        "canonical_query": case["canonical_query"],
        "research_question": case["research_question"],
        "target_branches": case.get("target_branches", []),
        "started_at": utc_now(),
        "timeout_seconds": None,
        "replay": True,
        "replay_mode": "rank_only",
        "with_context": False,
        "context_status": "disabled",
        "status": "ranking_replay",
        "progress": [],
        "retriever": {"enabled": False, "reason": "rank_only_replay"},
        "paper_calls": [],
        "llm_calls": [],
        "retriever_calls": [],
    }
    limits: list[str] = []
    candidates: list[dict[str, Any]] = []
    ranked: list[Any] = []
    ranking_method = "heuristic_no_recorded_judgments"
    old_map = None
    mapping_info: dict[str, Any] = {}
    judgment_info: dict[str, Any] = {}
    if replay_record is None:
        limits.append("replay source has no record for this case")
    else:
        old_map = replay_record.get("final_result")
        candidates = _recorded_candidates(replay_record)
        aliases, raw_judgments = _recorded_alias_payload(replay_record)
        alias_map, mapping_info = _map_recorded_aliases(aliases, candidates)
        mapped_judgments, judgment_info = _replay_judgments(
            module, raw_judgments, aliases, candidates, alias_map, mapping_info,
        )
        limits.extend(mapping_info.get("limits", []))
        limits.extend(judgment_info.get("limits", []))
        parsed_papers: list[Any] = []
        for index, candidate in enumerate(candidates):
            try:
                parsed_papers.append(module.Paper.model_validate(candidate))
            except Exception as exc:
                limits.append(f"candidate {index} could not be parsed: {type(exc).__name__}")
        if len(parsed_papers) != len(candidates):
            # A partial paper list could cause the ranker to silently change
            # the denominator.  Keep the replay visible and do not claim a
            # complete ranking when this happens.
            mapped_judgments = []
            judgment_info["mode"] = "heuristic_unparseable_candidates"
        try:
            if parsed_papers:
                ranker = module.PaperRanker(settings.rank_weights)
                ranking_method = judgment_info.get("mode", ranking_method)
                ranked = ranker.rank(
                    case["canonical_query"], parsed_papers, mapped_judgments,
                    settings.core_paper_limit,
                    "llm" if mapped_judgments else "pending",
                )
        except Exception as exc:
            limits.append(f"current PaperRanker failed: {type(exc).__name__}: {str(exc)[:180]}")
            ranked = []

    if isinstance(old_map, dict):
        old_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        source_phase = old_map.get("phase")
        if source_phase is not None:
            old_map["source_phase"] = source_phase
            old_map["phase"] = "preserved_unrevalidated"
        old_map["replay_annotation"] = {
            "map_revalidated": False,
            "ranking_replayed": True,
            "source_status": replay_record.get("status") if replay_record else None,
        }
    row["final_result"] = old_map
    row["preserved_map"] = {
        "available": isinstance(old_map, dict),
        "map_revalidated": False,
        "source_status": replay_record.get("status") if replay_record else None,
    }
    row["replay_result"] = {
        "phase": "ranking_replay",
        "analysis_source": "ranking_replay",
        "map_revalidated": False,
        "ranking_method": ranking_method,
        "candidate_count": len(candidates),
        "judgment_count": judgment_info.get("mapped_count", 0) or 0,
        "core_papers": jsonable(ranked),
    }
    row["replay_mapping"] = mapping_info
    row["replay_judgments"] = judgment_info
    row["limits"] = list(dict.fromkeys(limits))
    row["candidate_pool"] = candidates
    row["metrics"] = candidate_metrics(
        case, candidates, SimpleNamespace(core_papers=ranked) if ranked else None,
    )
    row["finished_at"] = utc_now()
    row["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    return row


async def run_case(module: SimpleNamespace, settings: Any, client: Any,
                   case: dict[str, Any], replay_record: dict[str, Any] | None,
                   timeout_seconds: float, *, with_context: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    row: dict[str, Any] = {
        "case_id": case["id"],
        "canonical_query": case["canonical_query"],
        "research_question": case["research_question"],
        "target_branches": case.get("target_branches", []),
        "started_at": utc_now(),
        "timeout_seconds": timeout_seconds,
        "replay": replay_record is not None,
        "with_context": with_context,
        "progress": [],
    }
    explorer, papers, llm, retriever, retriever_info = build_stack(module, settings, client, replay_record)
    row["retriever"] = retriever_info

    async def progress(event: dict[str, Any]) -> None:
        row["progress"].append({
            "type": event.get("type"),
            "stage": event.get("stage"),
            "elapsed_seconds": round(time.perf_counter() - started, 4),
        })

    node = None
    try:
        explore_kwargs: dict[str, Any] = {
            "mode": "live",
            "refresh": True,
            "progress": progress,
        }
        if with_context:
            explore_parameters = inspect.signature(explorer.explore).parameters
            context_parameter = next(
                (name for name in ("context", "research_question", "question") if name in explore_parameters),
                None,
            )
            if context_parameter is None:
                row["context_status"] = "unsupported_by_backend"
            else:
                explore_kwargs[context_parameter] = case["research_question"]
                row["context_status"] = context_parameter
        else:
            row["context_status"] = "disabled"
        node = await asyncio.wait_for(
            explorer.explore(case["canonical_query"], **explore_kwargs),
            timeout=timeout_seconds,
        )
        row["status"] = ("fallback" if node.paper_source == "demo" else
                         "complete" if node.phase == "complete" and node.analysis_source == "llm" else
                         str(node.phase) if node.phase != "complete" else "unverified_analysis")
        row["final_result"] = jsonable(node.model_dump(mode="json"))
    except asyncio.TimeoutError as exc:
        row["status"] = "timeout"
        row["error"] = error_record(exc)
    except BaseException as exc:
        row["status"] = "error"
        row["error"] = error_record(exc)
        row["traceback"] = traceback.format_exc(limit=8)
    finally:
        candidates: list[dict[str, Any]] = []
        for call in papers.calls:
            if call.get("method") == "search_papers" and isinstance(call.get("output"), list):
                candidates = call["output"]
                break
        if retriever is not None:
            # A new retriever may merge the original, anchor-citation and
            # alternative lanes into result.papers.  Prefer that exact result
            # for recall/type reporting; the legacy path retains first search.
            merged = [
                call.get("result_papers")
                for call in retriever.calls
                if isinstance(call.get("result_papers"), list) and call.get("result_papers")
            ]
            if merged:
                candidates = max(merged, key=len)
        row["candidate_pool"] = candidates
        row["paper_calls"] = papers.calls
        row["llm_calls"] = llm.calls
        row["retriever_calls"] = retriever.calls if retriever is not None else []
        verifier = getattr(retriever.inner, "metadata_verifier", None) if retriever is not None else None
        row["metadata_verification"] = jsonable(getattr(verifier, "last_report", None))
        row["metrics"] = candidate_metrics(case, candidates, node if row["status"] == "complete" else None)
        row["finished_at"] = utc_now()
        row["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    return row


def summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in cases if item.get("status") == "complete"]
    ranking_replays = [item for item in cases if item.get("status") == "ranking_replay"]
    recalls = [item["metrics"]["candidate_recall"] for item in cases if item.get("metrics", {}).get("candidate_recall") is not None]
    top8 = [item["metrics"]["top8_hit_count"] for item in cases if item.get("metrics")]
    return {
        "case_count": len(cases),
        "complete_count": len(completed),
        "ranking_replay_count": len(ranking_replays),
        "ranking_replay_limit_case_count": sum(bool(item.get("limits")) for item in ranking_replays),
        "timeout_count": sum(item.get("status") == "timeout" for item in cases),
        "error_count": sum(item.get("status") == "error" for item in cases),
        "fallback_count": sum(item.get("status") == "fallback" for item in cases),
        "live_complete_anchor_recall": {
            "found": sum(item["metrics"]["candidate_found_count"] for item in completed),
            "total": sum(item["metrics"]["anchor_count"] for item in completed),
        },
        # This is the unweighted mean of per-case recalls.  Keep the
        # aggregation name explicit so it is not confused with the pooled
        # anchor ratio below.
        "macro_avg_candidate_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "pooled_anchor_recall": {
            "found": sum(item["metrics"]["candidate_found_count"] for item in cases if item.get("metrics")),
            "total": sum(item["metrics"]["anchor_count"] for item in cases if item.get("metrics")),
            "ratio": round(
                sum(item["metrics"]["candidate_found_count"] for item in cases if item.get("metrics"))
                / sum(item["metrics"]["anchor_count"] for item in cases if item.get("metrics")),
                4,
            )
            if sum(item["metrics"]["anchor_count"] for item in cases if item.get("metrics"))
            else None,
        },
        "top8_hit_count_total": sum(top8),
        "top8_hit_case_count": sum(bool(item["metrics"].get("top8_hit")) for item in cases if item.get("metrics")),
    }


async def evaluate(args: argparse.Namespace) -> Path:
    requested_cases_path = resolve_path(args.cases)
    case_selector = args.case_ids
    if requested_cases_path.is_file():
        cases_path = requested_cases_path
    else:
        # Convenience form: --cases case-a,case-b while retaining the public
        # fixture as the source of truth.
        cases_path = DEFAULT_CASES
        case_selector = case_selector or args.cases
    all_cases = load_cases(cases_path)
    if case_selector:
        wanted = {item.strip() for item in re.split(r"[,\s]+", case_selector) if item.strip()}
        cases = [item for item in all_cases if item["id"] in wanted or item["canonical_query"] in wanted]
        missing = wanted - {item["id"] for item in cases} - {item["canonical_query"] for item in cases}
        if missing:
            raise SystemExit(f"unknown case ids: {', '.join(sorted(missing))}")
    else:
        cases = all_cases
    if not cases:
        raise SystemExit("no evaluation cases selected")
    output = output_file(args.output, args.label)
    if not runtime_only(output):
        raise SystemExit(f"raw evaluation output must stay under {REPO_ROOT / '.runtime'}: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    replay_path = resolve_path(args.replay) if args.replay else None
    replay = replay_index(replay_path) if replay_path else {}
    backend_root = resolve_path(args.backend_root)
    # Rank-only replay imports Paper/Settings/PaperRanker but deliberately
    # avoids importing or constructing FieldExplorer and any provider stack.
    module = import_backend(backend_root, include_explorer=replay_path is None)
    database_path = RUNTIME_ROOT / ("baseline.sqlite3" if args.label == "baseline" else f"{slug(args.label)}.sqlite3")
    settings = module.Settings(_env_file=str(REPO_ROOT / ".env"), database_path=str(database_path))
    metadata = {
        "schema_version": 1,
        "label": args.label,
        "mode": "ranking_replay" if replay_path else "live_benchmark",
        "replay_source": str(replay_path) if replay_path else None,
        "started_at": utc_now(),
        "cases_file": str(cases_path),
        "backend_root": str(backend_root),
        "database_path": str(database_path),
        "runtime_policy": {
            "parallelism": 1,
            "automatic_retries": 0,
            "max_seconds_per_case": args.timeout,
            "network_access": "disabled" if replay_path else "enabled",
        },
        "settings": {
            "llm_configured": bool(settings.llm_api_key),
            "llm_model_configured": bool(settings.llm_model.strip()),
            "llm_model": settings.llm_model,
            "openalex_key_configured": bool(settings.openalex_api_key),
            "search_limit": settings.search_limit,
            "core_paper_limit": settings.core_paper_limit,
            "llm_analysis_limit": settings.llm_analysis_limit,
            "request_timeout_seconds": settings.request_timeout_seconds,
            "llm_request_timeout_seconds": settings.llm_request_timeout_seconds,
        },
        "cases": [],
    }

    def persist_and_report(row: dict[str, Any]) -> None:
        metadata["cases"].append(row)
        metadata["summary"] = summary(metadata["cases"])
        metadata["updated_at"] = utc_now()
        output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "case_id": row["case_id"],
            "status": row["status"],
            "elapsed_seconds": row["elapsed_seconds"],
            "candidate_count": row["metrics"]["candidate_count"],
            "candidate_recall": row["metrics"]["candidate_recall"],
            "top8_hit_count": row["metrics"]["top8_hit_count"],
            "limits": row.get("limits", []),
            "ranking_method": (row.get("replay_result") or {}).get("ranking_method"),
            "error": row.get("error"),
        }, ensure_ascii=False), flush=True)

    if replay_path:
        for case in cases:
            persist_and_report(run_ranking_replay(module, settings, case, replay.get(case["id"])))
    else:
        async with __import__("httpx").AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            for case in cases:
                row = await run_case(
                    module,
                    settings,
                    client,
                    case,
                    None,
                    args.timeout,
                    with_context=args.with_context,
                )
                persist_and_report(row)
    metadata["finished_at"] = utc_now()
    metadata["summary"] = summary(metadata["cases"])
    output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(RUNTIME_ROOT), help="JSON file or runtime directory")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="fixture JSON path")
    parser.add_argument("--case-ids", default="", help="optional comma/space-separated case ids")
    parser.add_argument("--label", default="baseline", help="run label; baseline uses baseline.sqlite3")
    parser.add_argument("--backend-root", default=str(DEFAULT_BACKEND_ROOT), help="backend tree; rank-only replay uses only its current PaperRanker")
    parser.add_argument(
        "--replay", default="",
        help="prior evaluator JSON for offline rank-only replay (no FieldExplorer, LLM, or network)",
    )
    parser.add_argument("--timeout", type=float, default=CASE_TIMEOUT_SECONDS, help="per-case wall-clock limit")
    parser.add_argument(
        "--with-context",
        action="store_true",
        help="pass each fixture research_question when the backend explore API supports a context keyword",
    )
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > CASE_TIMEOUT_SECONDS:
        parser.error("--timeout must be in (0, 240]")
    return args


if __name__ == "__main__":
    asyncio.run(evaluate(parse_args()))
