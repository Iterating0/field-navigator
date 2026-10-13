import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.models.schemas import Decomposition, Paper
from app.providers.base import ProviderError
from app.providers.llm import CompatibleLLMProvider
from app.services.field_decomposer import FieldDecomposer


UNSUPPORTED_FORMAT = {'error': {
    'message': 'This response_format type is unavailable now',
    'type': 'invalid_request_error', 'param': None, 'code': 'invalid_request_error'}}
VALID_ANALYSIS = {'summary': 'Based on the supplied papers.', 'prerequisites': [],
                  'subfields': [], 'paper_judgments': []}


def completion(content=None):
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
        'content': json.dumps(VALID_ANALYSIS if content is None else content)}}]})


def settings(mode='auto', **kwargs):
    return Settings(_env_file=None, llm_api_key='test-key', llm_model='test-model',
                    llm_response_format=mode, **kwargs)


async def generate(provider):
    return await provider.generate_structured(system='Return JSON', payload={'field': 'test'},
                                              schema=Decomposition.model_json_schema())


def test_auto_prefers_strict_schema_when_supported():
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return completion()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            assert await generate(CompatibleLLMProvider(http, settings())) == VALID_ANALYSIS
    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0]['response_format']['type'] == 'json_schema'
    assert requests[0]['response_format']['json_schema']['strict'] is True


@pytest.mark.parametrize('status,error', [
    (400, UNSUPPORTED_FORMAT),
    (422, {'error': {'param': 'response_format', 'message': 'json_schema is not supported'}}),
])
def test_auto_falls_back_once_and_remembers_provider_capability(status, error):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        assert request.extensions['timeout']['read'] == 123
        if len(requests) == 1:
            return httpx.Response(status, json=error)
        return completion()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            provider = CompatibleLLMProvider(http, settings(llm_request_timeout_seconds=123))
            assert await generate(provider) == VALID_ANALYSIS
            assert await generate(provider) == VALID_ANALYSIS
    asyncio.run(run())
    assert [r['response_format']['type'] for r in requests] == ['json_schema', 'json_object', 'json_object']
    assert requests[0]['messages'] == requests[1]['messages']
    assert 'JSON schema:' in requests[1]['messages'][0]['content']
    assert requests[1]['model'] == 'test-model'


@pytest.mark.parametrize('status,error', [
    (400, {'error': {'message': 'Model not found'}}),
    (400, {'error': {'message': 'Invalid schema for response_format: unsupported keyword'}}),
    (400, {'error': {'param': 'response_format.json_schema.schema', 'message': 'Unsupported keyword'}}),
    (400, {'error': {'message': 'Context length exceeded'}}),
    (400, {'error': 'Bad request'}),
    (400, ['Bad request']),
    (401, UNSUPPORTED_FORMAT),
    (429, UNSUPPORTED_FORMAT),
    (500, UNSUPPORTED_FORMAT),
])
def test_auto_does_not_retry_unrelated_errors(status, error):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=error)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError, match=f'HTTP {status}'):
                await generate(CompatibleLLMProvider(http, settings()))
    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize('mode', ['json_schema', 'json_object'])
def test_explicit_modes_are_honored_without_fallback(mode):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json=UNSUPPORTED_FORMAT)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError, match='LLM_RESPONSE_FORMAT'):
                await generate(CompatibleLLMProvider(http, settings(mode)))
    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0]['response_format']['type'] == mode


def test_fallback_failure_is_not_retried_again():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(400, json=UNSUPPORTED_FORMAT)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError):
                await generate(CompatibleLLMProvider(http, settings()))
    asyncio.run(run())
    assert len(requests) == 2


def test_invalid_configuration_fails_before_network():
    def handle(request):
        pytest.fail('Invalid configuration must not send a request')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError, match='LLM_RESPONSE_FORMAT'):
                await generate(CompatibleLLMProvider(http, settings('invalid')))
    asyncio.run(run())


def test_invalid_json_mode_result_does_not_enter_cache(tmp_path):
    class Papers:
        async def search_papers(self, query, limit):
            return [Paper(id='W1', title='Two dimensional electron gas')]

    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json=UNSUPPORTED_FORMAT)
        return completion({'summary': 'Missing required fields'})

    async def run():
        config = settings(database_path=str(tmp_path / 'cache.db'))
        app = create_app(config)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                explorer = app.state.explorer
                explorer.papers = Papers()
                explorer.decomposer = FieldDecomposer(CompatibleLLMProvider(http, config))
                with pytest.raises(ProviderError, match='schema'):
                    await explorer.explore('two dimensional electron gas')
                assert explorer.cache.count() == 0
    asyncio.run(run())
    # Map and judgments now run concurrently; the invalid map can cancel the
    # other stage before or after it reaches the transport. Count negotiation
    # attempts in the dedicated transport tests, not this integration test.
    assert any(r['response_format']['type'] == 'json_object' for r in requests)


@pytest.mark.parametrize('base,mode,expected', [
    ('https://api.deepseek.com', 'auto', {'thinking': {'type': 'disabled'}}),
    ('https://api.deepseek.com/v1', 'auto', {'thinking': {'type': 'disabled'}}),
    ('https://api.deepseek.com.example.org', 'auto', {}),
    ('https://api.openai.com/v1', 'auto', {}),
    ('https://api.deepseek.com', 'provider', {}),
    ('https://api.deepseek.com', 'low', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}),
    ('https://api.deepseek.com', 'high', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}),
])
def test_thinking_controls_are_explicit_and_provider_scoped(base, mode, expected):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return completion()
    async def run():
        config = settings(llm_base_url=base, llm_thinking=mode)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            await generate(CompatibleLLMProvider(http, config))
    asyncio.run(run())
    assert {k: v for k, v in requests[0].items() if k in ('thinking', 'reasoning_effort')} == expected


def test_compact_ids_restore_evidence_and_judgments():
    class LLM:
        async def generate_structured(self, **kwargs):
            assert kwargs['payload']['papers'][0]['id'] == 'p1'
            return {'summary': 'Short summary', 'prerequisites': [], 'subfields': [
                {'name': 'Branch', 'reason': 'Supported direction', 'confidence': .8,
                 'evidence_paper_ids': ['p1', 'p999']}], 'paper_judgments': [
                {'paper_id': 'p1', 'importance': .8, 'relevance': .9, 'reason': 'Contribution'}]}
    paper = Paper(id='https://openalex.org/W123', title='Paper')
    result = asyncio.run(FieldDecomposer(LLM()).decompose('Field', [paper]))
    assert result.subfields[0].evidence_paper_ids == [paper.id]
    assert result.paper_judgments[0].paper_id == paper.id


def test_truncated_completion_is_actionable_and_rejected():
    def handle(request):
        assert json.loads(request.content)['max_tokens'] == 2048
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError, match='LLM_MAX_TOKENS'):
                await generate(CompatibleLLMProvider(http, settings(llm_max_tokens=2048)))
    asyncio.run(run())
