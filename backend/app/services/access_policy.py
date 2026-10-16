"""Bound uncached public explorations without charging offline or cached reads."""
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from app.models.schemas import normalize_field
from app.providers.base import ProviderError


class LiveRequestGate:
    def __init__(self, budget: int = 0, max_concurrency: int = 0):
        self.budget = budget
        self.max_concurrency = max_concurrency
        self.used = 0
        self.active = 0
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def admit(self, body, explorer,
                    cache_probe: Callable[[], Awaitable[object | None]] | None = None):
        language = getattr(body, 'language', 'zh-CN')
        english = language == 'en'
        if body.mode == 'demo' or not (self.budget or self.max_concurrency):
            yield
            return
        if not body.refresh:
            if cache_probe is not None:
                cached = await cache_probe()
            else:
                key = (explorer.cache_key(body.query, body.mode, getattr(body, 'research_question', None),
                                          getattr(body, 'language', 'zh-CN'))
                       if hasattr(explorer, 'cache_key') else
                       explorer.fingerprint + ':' + body.mode + ':' + normalize_field(body.query))
                cached = await asyncio.to_thread(explorer.cache.get, key)
            if cached is not None:
                yield
                return
        async with self.lock:
            if self.budget and self.used >= self.budget:
                raise ProviderError(
                    'The public live-analysis quota is exhausted. Cached results remain available; '
                    'you can also try the offline NHSE demo.' if english else
                    '公开体验的实时分析额度已用完。已有缓存仍可查看，或选择离线演示体验 NHSE 示例。',
                    429,
                )
            if self.max_concurrency and self.active >= self.max_concurrency:
                raise ProviderError(
                    'Another live analysis is in progress. Retry shortly or try the offline demo.'
                    if english else
                    '实时分析正在处理其他请求，请稍后重试；也可先体验离线演示。',
                    429,
                )
            self.used += 1
            self.active += 1
        try:
            yield
        finally:
            async with self.lock:
                self.active -= 1
