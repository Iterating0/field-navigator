import asyncio
import re
import httpx
from app.models.schemas import Paper
from app.providers.base import ProviderError


def reconstruct_abstract(index: dict | None) -> str | None:
    if not index:
        return None
    positions = [(pos, word) for word, offsets in index.items() for pos in offsets if pos < 2000]
    return ' '.join(word for _, word in sorted(positions))[:8000] or None


def parse_work(work: dict) -> Paper:
    location = work.get('primary_location') or {}
    source = location.get('source') or {}
    return Paper(
        id=work['id'], title=work.get('title') or work.get('display_name') or 'Untitled',
        year=work.get('publication_year'), citation_count=work.get('cited_by_count'),
        authors=[a['author']['display_name'] for a in work.get('authorships', [])
                 if a.get('author', {}).get('display_name')],
        doi=work.get('doi'), url=work.get('doi') or location.get('landing_page_url') or work['id'],
        abstract=reconstruct_abstract(work.get('abstract_inverted_index')),
        journal=source.get('display_name'), referenced_works=work.get('referenced_works') or [],
    )


class OpenAlexProvider:
    def __init__(self, client: httpx.AsyncClient, api_key: str = '', mailto: str = ''):
        self.client, self.api_key, self.mailto = client, api_key, mailto

    async def _get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        if self.mailto:
            params['mailto'] = self.mailto
        headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
        try:
            for attempt in range(2):
                response = await self.client.get('https://api.openalex.org/' + path,
                                                 params=params, headers=headers)
                if response.status_code >= 500 and attempt == 0:
                    await asyncio.sleep(.5)
                    continue
                if response.status_code == 429:
                    raise ProviderError('OpenAlex 额度或速率受限（429）。请配置 OPENALEX_API_KEY，或稍后重试。', 429)
                if response.status_code in (401, 403):
                    raise ProviderError('OpenAlex 拒绝访问，请检查 OPENALEX_API_KEY。', 502)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError('OpenAlex 请求超时，请稍后重试。', 504) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError('OpenAlex 暂时不可用，请检查网络连接后重试。') from exc
        raise ProviderError('OpenAlex 暂时不可用。')

    async def search_papers(self, query: str, limit: int = 40) -> list[Paper]:
        data = await self._get('works', {'search': query, 'per_page': min(limit, 100),
                                       'filter': 'is_retracted:false'})
        try:
            return list({p.id: p for p in map(parse_work, data.get('results', []))}.values())
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError('OpenAlex 返回的论文数据格式异常，请重试。') from exc

    async def get_paper(self, paper_id: str) -> Paper:
        identifier = paper_id.removeprefix('https://openalex.org/')
        if not re.fullmatch(r'W\d+', identifier):
            raise ProviderError('需要合法的 OpenAlex work ID。', 422)
        return parse_work(await self._get('works/' + identifier))

    async def get_citations(self, paper_id: str, limit: int = 40) -> list[Paper]:
        identifier = paper_id.removeprefix('https://openalex.org/')
        if not re.fullmatch(r'W\d+', identifier):
            raise ProviderError('需要合法的 OpenAlex work ID。', 422)
        data = await self._get('works', {'filter': f'cites:{identifier},is_retracted:false',
                                       'per_page': min(limit, 100)})
        return [parse_work(w) for w in data.get('results', [])]
