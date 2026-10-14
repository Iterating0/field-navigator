import asyncio
from copy import deepcopy
import json
import logging

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.models.schemas import Decomposition, Paper
from app.providers.base import ProviderError
from app.providers.llm import CompatibleLLMProvider, strictify_json_schema
from app.services.field_decomposer import FieldDecomposer


UNSUPPORTED_FORMAT = {'error': {
    'message': 'This response_format type is unavailable now',
    'type': 'invalid_request_error', 'param': None, 'code': 'invalid_request_error'}}
VALID_ANALYSIS = {'summary': 'Based on the supplied papers.', 'prerequisites': [],
                  'subfields': [], 'paper_judgments': []}


def completion(content=None):
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
        'content': json.dumps(VALID_ANALYSIS if content is None else content)}}]})


def raw_completion(content):
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
        'content': content}}]})


def settings(mode='auto', **kwargs):
    return Settings(_env_file=None, llm_api_key='test-key', llm_model='test-model',
                    llm_response_format=mode, **kwargs)


async def generate(provider):
    return await provider.generate_structured(system='Return JSON', payload={'field': 'test'},
                                              schema=Decomposition.model_json_schema())


def assert_strict_schema(node):
    """Small validator for the subset required by strict structured output."""
    if isinstance(node, list):
        for item in node:
            assert_strict_schema(item)
        return
    if not isinstance(node, dict):
        return
    assert 'default' not in node
    properties = node.get('properties')
    if node.get('type') == 'object' or isinstance(properties, dict):
        properties = properties if isinstance(properties, dict) else {}
        assert node.get('additionalProperties') is False
        assert node.get('required') == list(properties)
    for value in node.values():
        assert_strict_schema(value)


def test_strictify_schema_is_recursive_and_does_not_mutate_input():
    schema = {
        'type': 'object',
        'properties': {
            'title': {'type': 'string', 'default': 'untitled'},
            'nullable_branch': {
                'anyOf': [
                    {'type': 'object', 'properties': {
                        'label': {'type': 'string', 'default': 'unknown'},
                    }, 'required': []},
                    {'type': 'null'},
                ],
                'default': None,
            },
            'rows': {'type': 'array', 'items': {'$ref': '#/$defs/Row'}},
        },
        'required': ['title'],
        'additionalProperties': True,
        '$defs': {
            'Row': {
                'type': 'object',
                'properties': {'value': {'type': 'number', 'default': 0}},
                'default': {},
            },
        },
    }
    original = deepcopy(schema)

    normalized = strictify_json_schema(schema)

    assert schema == original
    assert normalized is not schema
    assert_strict_schema(normalized)
    assert normalized['required'] == ['title', 'nullable_branch', 'rows']
    assert normalized['properties']['nullable_branch']['anyOf'][0]['required'] == ['label']
    assert normalized['properties']['nullable_branch']['anyOf'][1] == {'type': 'null'}


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
    sent_schema = requests[0]['response_format']['json_schema']['schema']
    prompt_schema = json.loads(requests[0]['messages'][0]['content'].split('JSON schema:\n', 1)[1])
    assert sent_schema == prompt_schema
    assert_strict_schema(sent_schema)


def test_auto_does_not_retry_invalid_schema_even_when_error_mentions_unsupported():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(400, json={'error': {
            'message': 'response_format schema is invalid and not supported',
        }})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError, match='HTTP 400'):
                await generate(CompatibleLLMProvider(http, settings()))
    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize('status,error', [
    (400, UNSUPPORTED_FORMAT),
    (422, {'error': {'param': 'response_format', 'message': 'json_schema is not supported'}}),
    (400, {'error': {
        'param': 'response_format',
        'message': 'Invalid parameter: response_format json_schema is not supported with this model',
    }}),
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
    paper = Paper(
        id='https://openalex.org/W123',
        title='Paper',
        abstract='This abstract supports branch evidence.',
    )

    class LLM:
        def __init__(self):
            self.calls = 0

        async def generate_structured(self, **kwargs):
            self.calls += 1
            if 'independent evidence auditor' in kwargs['system']:
                assert kwargs['payload']['papers'][0]['id'] == paper.id
                return {'audits': [{
                    'relation_id': 'r1',
                    'verdict': 'supported',
                    'reason': '摘要直接支持该关系。',
                }]}
            assert kwargs['payload']['papers'][0]['id'] == 'p1'
            return {'summary': 'Short summary', 'prerequisites': [], 'subfields': [
                {'name': 'Branch', 'reason': 'Supported direction', 'confidence': .8,
                 'evidence_paper_ids': ['p1', 'p999'],
                 'evidence_quotes': [{
                     'paper_id': 'p1', 'source': 'abstract',
                     'quote': 'supports branch evidence',
                 }]}], 'paper_judgments': [
                {'paper_id': 'p1', 'importance': .8, 'relevance': .9, 'reason': 'Contribution',
                 'evidence_quote': 'supports branch evidence'}]}

    llm = LLM()
    result = asyncio.run(FieldDecomposer(llm).decompose('Field', [paper]))
    assert llm.calls == 2
    assert result.subfields[0].evidence_paper_ids == [paper.id]
    assert result.subfields[0].evidence_quotes[0].paper_id == paper.id
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


def test_valid_unicode_and_json_escapes_keep_their_original_semantics():
    expected = {
        'summary': '拓扑相变 α 与 literal \\alpha',
        'prerequisites': [], 'subfields': [], 'paper_judgments': [],
    }
    content = json.dumps(expected, ensure_ascii=False)

    def handle(request):
        return raw_completion(content)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            return await generate(CompatibleLLMProvider(http, settings()))

    assert asyncio.run(run()) == expected


def test_invalid_latex_escapes_are_repaired_without_changing_provenance():
    content = r'''{"summary":"Band \alpha and \Delta","prerequisites":[],"subfields":[{"name":"Branch","reason":"Evidence \Delta","confidence":0.8,"evidence_paper_ids":["W1"],"evidence_quotes":[{"paper_id":"W1","source":"abstract","quote":"Observed \sigma_{xx}"}]}],"paper_judgments":[{"paper_id":"W1","importance":0.8,"relevance":0.9,"reason":"Uses \hat{H}","evidence_quote":"Eq. \alpha"}]}'''

    def handle(request):
        return raw_completion(content)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            return await generate(CompatibleLLMProvider(http, settings()))

    result = asyncio.run(run())
    assert result['summary'] == r'Band \alpha and \Delta'
    assert result['subfields'][0]['evidence_quotes'][0] == {
        'paper_id': 'W1', 'source': 'abstract', 'quote': r'Observed \sigma_{xx}'
    }
    assert result['paper_judgments'][0]['evidence_quote'] == r'Eq. \alpha'


def test_whole_json_fence_is_unwrapped_but_trailing_commentary_is_rejected():
    fenced = '```json\n' + json.dumps(VALID_ANALYSIS, ensure_ascii=False) + '\n```'

    def handle(request):
        return raw_completion(fenced)

    async def run_fenced():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            return await generate(CompatibleLLMProvider(http, settings()))

    assert asyncio.run(run_fenced()) == VALID_ANALYSIS

    requests = []
    def trailing_handle(request):
        requests.append(request)
        return raw_completion(fenced + '\ncommentary')

    async def run_trailing():
        async with httpx.AsyncClient(transport=httpx.MockTransport(trailing_handle)) as http:
            with pytest.raises(ProviderError, match='LLM 响应无效'):
                await generate(CompatibleLLMProvider(http, settings()))

    asyncio.run(run_trailing())
    assert len(requests) == 1


def test_raw_newline_inside_json_string_is_escaped_without_loss():
    content = '{"summary":"line one' + '\n' + 'line two","prerequisites":[],"subfields":[],"paper_judgments":[]}'

    def handle(request):
        return raw_completion(content)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            return await generate(CompatibleLLMProvider(http, settings()))

    assert asyncio.run(run())['summary'] == 'line one\nline two'


def test_incomplete_json_is_still_rejected_after_narrow_repair(caplog):
    content = r'{"summary":"Band \alpha","prerequisites":[],"subfields":[],"paper_judgments":[]'

    def handle(request):
        return raw_completion(content)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError, match='LLM 响应无效'):
                await generate(CompatibleLLMProvider(http, settings()))

    caplog.set_level(logging.ERROR, logger='app.providers.llm')
    asyncio.run(run())
    record = next(record for record in caplog.records if record.name == 'app.providers.llm')
    assert 'type=JSONDecodeError' in record.getMessage()
    assert 'line=' in record.getMessage() and 'col=' in record.getMessage()
    assert f'len={len(content)}' in record.getMessage()
    assert 'Band' not in record.getMessage()


def test_invalid_json_does_not_trigger_a_per_content_network_retry():
    content = r'{"summary":"Band \alpha","prerequisites":[],"subfields":[],"paper_judgments":[]'
    requests = []

    def handle(request):
        requests.append(request)
        return raw_completion(content)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ProviderError):
                await generate(CompatibleLLMProvider(http, settings()))

    asyncio.run(run())
    assert len(requests) == 1
