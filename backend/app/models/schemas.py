import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class FieldRelation(StrictModel):
    name: str = Field(min_length=2, max_length=180)
    reason: str = Field(min_length=1, max_length=1500)
    confidence: float = Field(ge=0, le=1)
    evidence_paper_ids: list[str]


class PaperJudgment(StrictModel):
    paper_id: str
    importance: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)


class Decomposition(StrictModel):
    summary: str = Field(min_length=1, max_length=6000)
    prerequisites: list[FieldRelation] = Field(max_length=5)
    subfields: list[FieldRelation] = Field(max_length=7)
    paper_judgments: list[PaperJudgment] = Field(max_length=100)


class CorePaper(BaseModel):
    paper: Paper
    score: float = Field(ge=0, le=1)
    reason: str
    signals: dict[str, float] = Field(default_factory=dict)


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


class ExploreRequest(BaseModel):
    query: str = Field(min_length=2, max_length=180)
    mode: Literal['auto', 'live', 'demo'] = 'auto'
    refresh: bool = False

    @field_validator('query')
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = ' '.join(value.split())
        if len(value) < 2:
            raise ValueError('请输入至少两个字符的领域名称')
        return value
