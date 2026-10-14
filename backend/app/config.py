from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    openalex_api_key: str = ''
    openalex_mailto: str = ''
    llm_api_key: str = ''
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_model: str = ''
    llm_response_format: str = 'auto'
    llm_thinking: Literal['auto', 'provider', 'disabled', 'low', 'high'] = 'auto'
    llm_max_tokens: int = Field(default=16384, ge=1024, le=65536)
    llm_analysis_limit: int = Field(default=0, ge=0, le=100)
    database_path: str = 'backend/data/field_navigator.sqlite3'
    cache_ttl_hours: int = Field(default=168, ge=1)
    search_cache_ttl_hours: int = Field(default=24, ge=1)
    search_limit: int = Field(default=40, ge=5, le=100)
    core_paper_limit: int = Field(default=8, ge=1, le=10)
    request_timeout_seconds: float = Field(default=45, gt=0, le=120)
    llm_request_timeout_seconds: float = Field(default=180, gt=0, le=240)
    resolve_timeout_seconds: float = Field(default=30, gt=0, le=120)
    resolve_probe_limit: int = Field(default=6, ge=1, le=20)
    resolve_cache_ttl_hours: int = Field(default=24, ge=1)
    frontend_dist_path: str = ''
    # Optional limits for a single-process public preview; local use stays unlimited.
    live_request_budget: int = Field(default=0, ge=0)
    live_max_concurrency: int = Field(default=0, ge=0)
    rank_citation: float = Field(default=.20, ge=0)
    rank_age_normalized: float = Field(default=.15, ge=0)
    rank_relevance: float = Field(default=.30, gt=0)
    rank_shared_references: float = Field(default=.10, ge=0)
    rank_llm_importance: float = Field(default=.25, ge=0)

    @property
    def thinking_options(self) -> dict:
        mode = self.llm_thinking
        if mode == 'auto':
            mode = 'disabled' if urlparse(self.llm_base_url).hostname == 'api.deepseek.com' else 'provider'
        if mode == 'provider':
            return {}
        if mode == 'disabled':
            return {'thinking': {'type': 'disabled'}}
        return {'thinking': {'type': 'enabled'}, 'reasoning_effort': mode}

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path)
        return path if path.is_absolute() else ROOT / path

    @property
    def rank_weights(self) -> dict[str, float]:
        return {key: getattr(self, f'rank_{key}') for key in
                ('citation', 'age_normalized', 'relevance', 'shared_references', 'llm_importance')}
