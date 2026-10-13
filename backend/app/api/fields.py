import asyncio
import json
import logging
from contextlib import nullcontext
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.models.schemas import ExploreRequest, FieldNode
from app.providers.base import ProviderError

router = APIRouter(prefix='/api/fields', tags=['fields'])


def admission(body, request):
    gate = getattr(request.app.state, 'live_gate', None)
    return gate.admit(body, request.app.state.explorer) if gate is not None else nullcontext()


@router.post('/explore', response_model=FieldNode)
async def explore(body: ExploreRequest, request: Request):
    async with admission(body, request):
        return await request.app.state.explorer.explore(body.query, body.mode, body.refresh)


@router.post('/explore/stream')
async def explore_stream(body: ExploreRequest, request: Request):
    async def events():
        queue = asyncio.Queue(maxsize=8)

        async def run():
            try:
                async with admission(body, request):
                    result = await request.app.state.explorer.explore(body.query, body.mode, body.refresh, queue.put)
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
