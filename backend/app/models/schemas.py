import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

CURRENT_QUALITY_REVISION = 28

# Keep the wire value intentionally small and explicit.  These values are also
# part of analysis/cache keys, so do not silently infer a locale from a free
# form user string in the service layer.
Language = Literal['zh-CN', 'en']
DEFAULT_LANGUAGE: Language = 'zh-CN'


def normalize_field(name: str) -> str:
    value = unicodedata.normalize('NFKC', name).strip().lower()
    value = re.sub(r'[‐‑‒–—−_]', '-', value)
    value = re.sub(r'\s*-\s*', '-', value)
    value = ' '.join(value.split())
    aliases = {'nhse': 'non-hermitian skin effect',
               '非厄米趋肤效应': 'non-hermitian skin effect',
               'non hermitian skin effect': 'non-hermitian skin effect',
               'incoherent non-hermitian skin effect': 'incoherent nhse'}
    return aliases.get(value, value)


def field_id(name: str) -> str:
    return hashlib.sha256(normalize_field(name).encode()).hexdigest()[:16]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Paper(BaseModel):
    id: str
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    citation_count: int | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    journal: str | None = None
    referenced_works: list[str] = Field(default_factory=list)
    source: str = 'openalex'
    work_type: str | None = None
    work_version: str | None = None
    is_retracted: bool = False
    is_paratext: bool = False
    source_record_ids: list[str] = Field(default_factory=list)
    abstract_source_record_id: str | None = None


class EvidenceQuote(StrictModel):
    paper_id: str
    source: Literal['abstract', 'title']
    quote: str = Field(min_length=1, max_length=300)


class FieldRelation(StrictModel):
    name: str = Field(min_length=2, max_length=180)
    reason: str = Field(min_length=1, max_length=1500)
    confidence: float = Field(ge=0, le=1)
    evidence_paper_ids: list[str]
    evidence_status: Literal['supported', 'weak', 'unverified'] = 'unverified'
    # Coverage of a research direction is distinct from proving a mechanism.
    claim_level: Literal['research_direction', 'theory_or_proposed', 'title_only'] = 'research_direction'
    evidence_quotes: list[EvidenceQuote] = Field(default_factory=list, max_length=3)
    evidence_warnings: list[str] = Field(default_factory=list)


class PaperJudgment(StrictModel):
    paper_id: str
    importance: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    role: Literal['primary', 'review', 'background', 'non_research', 'unknown'] = 'unknown'
    evidence_basis: Literal['abstract', 'title', 'unverified'] = 'unverified'
    evidence_quote: str = Field(default='', max_length=300)
    # Internal coverage annotation from the paper-judgment phase.  These IDs
    # are request-scoped retrieval needs, never scientific evidence; the
    # decomposition stage clears them when the supplied quote is not an exact
    # abstract excerpt.  A default keeps legacy stubs and cached judgments
    # source-compatible.
    evidence_need_ids: list[str] = Field(default_factory=list, max_length=3)


class Decomposition(StrictModel):
    summary: str = Field(min_length=1, max_length=6000)
    prerequisites: list[FieldRelation] = Field(max_length=5)
    subfields: list[FieldRelation] = Field(max_length=7)
    paper_judgments: list[PaperJudgment] = Field(max_length=100)
    warnings: list[str] = Field(default_factory=list)
    evidence_audit_complete: bool | None = None


class CorePaper(BaseModel):
    paper: Paper
    score: float = Field(ge=0, le=1)
    reason: str
    signals: dict[str, float] = Field(default_factory=dict)
    role: Literal['primary', 'review', 'background', 'non_research', 'unknown'] = 'unknown'
    evidence_basis: Literal['abstract', 'title', 'unverified'] = 'unverified'
    evidence_quote: str = Field(default='', max_length=300)


class FieldNode(BaseModel):
    id: str
    name: str
    summary: str
    prerequisites: list[FieldRelation]
    subfields: list[FieldRelation]
    core_papers: list[CorePaper]
    paper_source: Literal['openalex', 'demo']
    analysis_source: Literal['llm', 'mock', 'pending']
    phase: Literal['papers', 'map', 'complete'] = 'complete'
    candidate_count: int
    analyzed_paper_count: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cache_hit: bool = False
    # Relations may cite papers outside the ranked core-paper shortlist.
    # Keep this optional at the payload boundary so old cached maps still load.
    evidence_papers: list[Paper] = Field(default_factory=list)
    quality_revision: int = 0  # A missing field means legacy/unverified semantics.
    search_queries: list[str] = Field(default_factory=list)
    research_question: str | None = None
    # Missing on pre-bilingual cache entries means the original Simplified
    # Chinese output.  Keeping a default makes old persisted responses safe to
    # read while new language-specific keys prevent cross-locale reuse.
    language: Language = DEFAULT_LANGUAGE


class ExploreRequest(BaseModel):
    query: str = Field(min_length=2, max_length=180)
    mode: Literal['auto', 'live', 'demo'] = 'auto'
    refresh: bool = False
    research_question: str | None = Field(default=None, max_length=1000)
    language: Language = DEFAULT_LANGUAGE

    @field_validator('research_question')
    @classmethod
    def clean_research_question(cls, value: str | None) -> str | None:
        return ' '.join(value.split()) or None if value else None

    @field_validator('query')
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = ' '.join(value.split())
        if len(value) < 2:
            raise ValueError('请输入至少两个字符的领域名称')
        return value


class ResolveRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    mode: Literal['auto', 'live', 'demo'] = 'auto'
    refresh: bool = False
    language: Language = DEFAULT_LANGUAGE

    @field_validator('query')
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = ' '.join(value.split())
        if len(value) < 2:
            raise ValueError('请输入至少两个字符的研究主题或领域描述')
        return value


class ResolveCandidate(StrictModel):
    query: str = Field(min_length=2, max_length=180)
    name: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=600)
    evidence_papers: list[Paper] = Field(default_factory=list)


class ResolveResult(StrictModel):
    query: str = Field(min_length=2, max_length=1000)
    status: Literal['ready', 'choose', 'clarify']
    message: str = Field(min_length=1, max_length=1000)
    source: Literal['llm', 'alias', 'direct']
    candidates: list[ResolveCandidate] = Field(max_length=3)
    # Old resolver artifacts validate as Chinese through the default; the
    # resolver still checks this value against the requested cache key.
    language: Language = DEFAULT_LANGUAGE
