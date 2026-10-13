from typing import Any, Protocol
from app.models.schemas import Paper


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class PaperProvider(Protocol):
    async def search_papers(self, query: str, limit: int = 40) -> list[Paper]: ...
    async def get_paper(self, paper_id: str) -> Paper: ...
    async def get_citations(self, paper_id: str, limit: int = 40) -> list[Paper]: ...


class LLMProvider(Protocol):
    async def generate_structured(self, *, system: str, payload: dict[str, Any],
                                  schema: dict[str, Any]) -> dict[str, Any]: ...
