import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.demo import PAPERS
from app.main import create_app
from app.models.schemas import ExploreRequest
from app.providers.base import ProviderError
from app.services.access_policy import LiveRequestGate


@pytest.mark.parametrize('model, ready', [('', False), ('example-model', True)])
def test_health_distinguishes_missing_model_without_disclosing_key(tmp_path, model, ready):
    settings = Settings(_env_file=None, llm_api_key='private-test-value', llm_model=model,
                        database_path=str(tmp_path / 'cache.db'))
    with TestClient(create_app(settings)) as client:
        response = client.get('/api/health')
        assert response.json()['llm_configured']
        assert response.json()['llm_ready'] is ready
        assert 'private-test-value' not in response.text


def test_single_container_serves_ui_and_keeps_missing_api_and_assets_404(tmp_path):
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<html>Field Navigator</html>', encoding='utf-8')
    (dist / 'assets' / 'app-test.js').write_text('window.ready=true', encoding='utf-8')
    settings = Settings(_env_file=None, llm_api_key='', database_path=str(tmp_path / 'cache.db'),
                        frontend_dist_path=str(dist))
    with TestClient(create_app(settings)) as client:
        assert 'Field Navigator' in client.get('/').text
        assert client.get('/explore/NHSE').status_code == 200
        assert client.get('/api/health').json()['status'] == 'ok'
        assert not client.get('/api/health').json()['llm_ready']
        assert client.get('/api/missing').status_code == 404
        assert client.get('/assets/missing.js').status_code == 404
        assert client.get('/assets/app-test.js').headers['cache-control'].endswith('immutable')
        assert client.get('/').headers['cache-control'] == 'no-cache'


def test_exhausted_live_budget_preserves_cached_and_offline_exploration(tmp_path):
    settings = Settings(_env_file=None, llm_api_key='', database_path=str(tmp_path / 'cache.db'),
                        live_request_budget=1, live_max_concurrency=1)

    class Papers:
        calls = 0

        async def search_papers(self, *args):
            self.calls += 1
            return PAPERS[:5]

    with TestClient(create_app(settings)) as client:
        papers = Papers()
        client.app.state.explorer.papers = papers
        body = {'query': 'NHSE', 'mode': 'live'}
        first = client.post('/api/fields/explore', json=body)
        assert first.status_code == 200
        assert first.json()['phase'] == 'papers'
        assert first.json()['analysis_source'] == 'pending'
        assert client.post('/api/fields/explore', json=body).status_code == 429
        denied = client.post('/api/fields/explore', json={**body, 'refresh': True})
        assert denied.status_code == 429
        assert papers.calls == 1
        assert client.post('/api/fields/explore', json={'query': 'NHSE', 'mode': 'demo'}).status_code == 200
        stream = client.post('/api/fields/explore/stream', json={'query': 'new topic', 'mode': 'live'})
        assert '"type": "error"' in stream.text and '"status": 429' in stream.text
        assert '"type": "complete"' not in stream.text
        assert client.app.state.live_gate.active == 0


def test_cancellation_releases_concurrency_without_refunding_attempt_budget():
    async def run():
        class Cache:
            def get(self, key):
                return None

        explorer = SimpleNamespace(fingerprint='test', cache=Cache())
        gate = LiveRequestGate(budget=3, max_concurrency=1)
        body = ExploreRequest(query='test', mode='live')
        started = asyncio.Event()

        async def pending():
            async with gate.admit(body, explorer):
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(pending())
        await started.wait()
        with pytest.raises(ProviderError):
            async with gate.admit(body, explorer):
                pytest.fail('concurrent external analysis must not start')
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.active == 0 and gate.used == 1
        async with gate.admit(body, explorer):
            assert gate.active == 1
        assert gate.active == 0 and gate.used == 2

    asyncio.run(run())
