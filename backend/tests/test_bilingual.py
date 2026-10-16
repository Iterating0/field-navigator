import asyncio

from app.config import Settings
from app.data.demo import PAPERS
from app.db.cache import FieldCache
from app.models.schemas import ExploreRequest, FieldNode, ResolveRequest
from app.providers.mock import MockLLMProvider
from app.services.field_decomposer import FieldDecomposer
from app.services.query_resolver import QueryResolver
from app.services.evidence_verifier import localize_evidence_warnings
from app.services.field_explorer import _localize_retrieval_warning
from app.models.schemas import Paper


def test_language_is_explicit_and_legacy_nodes_default_to_chinese():
    assert ExploreRequest(query='NHSE').language == 'zh-CN'
    assert ResolveRequest(query='NHSE').language == 'zh-CN'
    assert FieldNode.model_validate({
        'id': 'x', 'name': 'Topic', 'summary': '摘要', 'prerequisites': [],
        'subfields': [], 'core_papers': [], 'paper_source': 'demo',
        'analysis_source': 'mock', 'candidate_count': 0,
    }).language == 'zh-CN'


def test_demo_provider_generates_english_explanations_without_translating_paper_metadata():
    async def run():
        provider = MockLLMProvider()
        common = {'field': 'NHSE', 'papers': [PAPERS[0].model_dump()]}
        zh = await provider.generate_structured(system='', payload={**common, 'language': 'zh-CN'}, schema={})
        en = await provider.generate_structured(system='', payload={**common, 'language': 'en'}, schema={})
        return zh, en

    zh, en = asyncio.run(run())
    assert zh['summary'] != en['summary']
    assert en['summary'].isascii()
    assert en['paper_judgments'][0]['reason'].isascii()
    assert en['paper_judgments'][0]['paper_id'] == PAPERS[0].id


def test_english_gate_warnings_are_localized_without_touching_paper_ids():
    warnings = localize_evidence_warnings([
        '关系“W1”未获元数据支持，已删除。',
        '摘录无法在实际发送的标题或摘要中核对，未作为支持证据。',
    ], 'en')
    assert warnings[0] == 'Relation “W1” lacked metadata support and was removed.'
    assert 'W1' in warnings[0]
    assert 'excerpt' in warnings[1].lower()
    selection_warnings = localize_evidence_warnings([
        '独立审查返回了未知摘录 ID，已忽略。',
        '独立审查未选择的摘录不作为该关系的支持证据。',
    ], 'en')
    assert 'unknown excerpt ID' in selection_warnings[0]
    assert 'excluded' in selection_warnings[1]


def test_english_arxiv_status_warnings_preserve_status_and_version_boundary():
    warnings = [
        'arXiv 条目 2401.12345 明确标记为 withdrawn，已排除该预印本的摘要和引用证据。',
        'arXiv 条目 2401.12345 明确标记为 withdrawn，仅记录链接状态，未将正式发表版本标记为撤稿。',
        'arXiv 条目 2401.12345 的 DOI 注册元数据未提供当前撤回状态，仅保留题名身份，摘要未作为证据使用。',
        'arXiv API 路径暂不可用；已使用 arXiv 的 DOI 注册元数据核查，当前撤回状态仍未核查，仅保留题名身份。',
    ]
    localized = [_localize_retrieval_warning(warning, 'en') for warning in warnings]
    assert all(text.isascii() for text in localized)
    assert '2401.12345' in localized[0] and 'withdrawn' in localized[0]
    assert 'published version was not marked retracted' in localized[1]
    assert 'abstract was not used as evidence' in localized[2]
    assert 'status remains unverified' in localized[3]
    assert [_localize_retrieval_warning(warning, 'zh-CN') for warning in warnings] == warnings


class _ResolverLLM:
    def __init__(self):
        self.systems = []

    async def generate_structured(self, **kwargs):
        self.systems.append(kwargs['system'])
        return {'candidates': [{
            'query': 'quantum transport',
            'name': 'Quantum transport',
            'summary': 'A target matched by an exact paper search.',
        }]}


class _Papers:
    def __init__(self):
        self.calls = 0

    async def search_papers(self, query, limit=40):
        self.calls += 1
        return [Paper(id='W1', title='Quantum transport evidence', abstract='Evidence')]


def test_resolver_isolates_language_results_but_reuses_language_neutral_probe_cache(tmp_path):
    async def run():
        settings = Settings(_env_file=None, llm_api_key='key', llm_model='model',
                            database_path=str(tmp_path / 'bilingual.db'))
        llm = _ResolverLLM()
        papers = _Papers()
        resolver = QueryResolver(settings, llm, papers, FieldCache(settings.db_path))
        query = '我想研究量子输运'
        zh = await resolver.resolve(query, 'live', language='zh-CN')
        en = await resolver.resolve(query, 'live', language='en')
        cached_zh = await resolver.cached(query, 'live', 'zh-CN')
        cached_en = await resolver.cached(query, 'live', 'en')
        return zh, en, cached_zh, cached_en, llm, papers

    zh, en, cached_zh, cached_en, llm, papers = asyncio.run(run())
    assert zh.language == cached_zh.language == 'zh-CN'
    assert en.language == cached_en.language == 'en'
    assert papers.calls == 1
    assert len(llm.systems) == 2
    assert 'Simplified Chinese' in llm.systems[0]
    assert 'concise English' in llm.systems[1]


def test_field_decomposer_passes_output_language_to_model_without_changing_topic_names():
    class LLM:
        def __init__(self):
            self.payload = None
            self.system = None

        async def generate_structured(self, **kwargs):
            self.payload = kwargs['payload']
            self.system = kwargs['system']
            return {
                'paper_judgments': [{
                    'paper_id': 'W1', 'importance': .8, 'relevance': .9,
                    'reason': 'Directly matches the requested topic.',
                }],
            }

    async def run():
        llm = LLM()
        paper = Paper(id='W1', title='Quantum transport evidence', abstract='Evidence')
        result = await FieldDecomposer(llm, require_evidence=False).judge_papers(
            'Quantum transport', [paper], language='en')
        return llm, result

    llm, result = asyncio.run(run())
    assert result[0].reason.startswith('Directly')
    assert llm.payload['language'] == 'en'
    assert 'concise English' in llm.system
