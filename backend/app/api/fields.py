import asyncio
import json
import logging
from contextlib import nullcontext
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.models.schemas import ExploreRequest, FieldNode, ResolveRequest, ResolveResult
from app.providers.base import ProviderError

router = APIRouter(prefix='/api/fields', tags=['fields'])

_DISCONNECT_POLL_SECONDS = 0.05


def admission(body, request, cache_probe=None):
    gate = getattr(request.app.state, 'live_gate', None)
    return gate.admit(body, request.app.state.explorer, cache_probe=cache_probe) if gate is not None else nullcontext()


async def _watch_client_disconnect(request: Request):
    """Wait until the ASGI request reports that its client has gone away."""
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(_DISCONNECT_POLL_SECONDS)


async def _resolve_live_with_disconnect_watch(resolver, request: Request,
                                              query: str, mode: str, refresh: bool):
    """Cancel a live resolver that would otherwise outlive a disconnected client."""
    resolve_task = asyncio.create_task(resolver.resolve(query, mode, refresh))
    disconnect_task = asyncio.create_task(_watch_client_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            (resolve_task, disconnect_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        # If both finish in the same event-loop turn, preserve the completed
        # resolver result rather than converting a successful response to 499.
        if resolve_task in done:
            return resolve_task.result()

        resolve_task.cancel()
        await asyncio.gather(resolve_task, return_exceptions=True)
        raise HTTPException(status_code=499, detail='客户端已断开，解析已取消。')
    finally:
        disconnect_task.cancel()
        resolve_task.cancel()
        await asyncio.gather(resolve_task, disconnect_task, return_exceptions=True)


@router.post('/explore', response_model=FieldNode)
async def explore(body: ExploreRequest, request: Request):
    async with admission(body, request):
        return await request.app.state.explorer.explore(body.query, body.mode, body.refresh,
                                                         allow_partial=True,
                                                         research_question=body.research_question)


@router.post('/resolve', response_model=ResolveResult)
async def resolve(body: ResolveRequest, request: Request):
    resolver = request.app.state.resolver
    # Alias/direct/demo resolution has no external cost.  A cached LLM result
    # also bypasses the live gate; only a cache miss may call the model/search.
    if resolver.requires_live(body.query, body.mode):
        cached = None if body.refresh else await resolver.cached(body.query, body.mode)
        if cached is None:
            async def cache_probe():
                return await resolver.cached(body.query, body.mode)
            async with admission(body, request, cache_probe=cache_probe):
                return await _resolve_live_with_disconnect_watch(
                    resolver, request, body.query, body.mode, body.refresh)
    return await resolver.resolve(body.query, body.mode, body.refresh)


@router.post('/explore/stream')
async def explore_stream(body: ExploreRequest, request: Request):
    async def events():
        queue = asyncio.Queue(maxsize=8)

        async def run():
            try:
                async with admission(body, request):
                    result = await request.app.state.explorer.explore(
                        body.query, body.mode, body.refresh, queue.put, allow_partial=True,
                        research_question=body.research_question)
                await queue.put({'type': 'complete', 'field': result.model_dump()})
            except ProviderError as exc:
                await queue.put({'type': 'error', 'detail': str(exc), 'status': exc.status_code})
            except Exception:
                logging.getLogger(__name__).exception('Exploration stream failed')
                await queue.put({'type': 'error', 'detail': '分析失败，请重试。', 'status': 500})

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False) + '\n'
                if event['type'] in ('complete', 'error'):
                    break
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(events(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
