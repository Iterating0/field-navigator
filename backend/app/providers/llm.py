import json
import logging
import time
from typing import Any
import httpx
from app.config import Settings
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)


def schema_format_unavailable(response: httpx.Response) -> bool:
    """Retry only an explicit format capability error, never an arbitrary 400."""
    if response.status_code not in (400, 422):
        return False
    try:
        error = response.json().get('error', {})
        if not isinstance(error, dict):
            return False
        message = str(error.get('message', '')).lower()
        param = str(error.get('param', '')).lower()
    except (ValueError, AttributeError):
        return False
    # Invalid schema contents must remain visible instead of weakening the request.
    if ('invalid schema' in message or 'schema for response_format' in message
            or param.startswith('response_format.json_schema.schema')):
        return False
    mentions_format = any(value in message or value in param
                          for value in ('response_format', 'json_schema'))
    unsupported = any(value in message for value in (
        'not supported', 'unsupported', 'unavailable', 'not available', 'does not support'))
    return mentions_format and unsupported


class CompatibleLLMProvider:
    """Transport only. No field-specific logic or model SDK dependency."""
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings
        self._schema_unavailable = False

    async def generate_structured(self, *, system: str, payload: dict[str, Any],
                                  schema: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.llm_model:
            raise ProviderError('已设置 LLM key，但缺少 LLM_MODEL。请在 .env 指定模型名称。', 503)
        mode = self.settings.llm_response_format
        if mode not in ('auto', 'json_schema', 'json_object'):
            raise ProviderError('LLM_RESPONSE_FORMAT 必须为 auto、json_schema 或 json_object。', 503)
        response_format: dict[str, Any] = {'type': 'json_object'}
        if mode == 'json_schema' or (mode == 'auto' and not self._schema_unavailable):
            response_format = {'type': 'json_schema', 'json_schema': {
                'name': 'field_analysis', 'strict': True, 'schema': schema}}
        body = {'model': self.settings.llm_model, 'response_format': response_format,
                'messages': [{'role': 'system', 'content': system + '\nJSON schema:\n' + json.dumps(schema)},
                             {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        body.update(self.settings.thinking_options)
        body['max_tokens'] = self.settings.llm_max_tokens
        url = self.settings.llm_base_url.rstrip('/') + '/chat/completions'
        headers = {'Authorization': f'Bearer {self.settings.llm_api_key}'}
        timeout = self.settings.llm_request_timeout_seconds
        started = time.perf_counter()
        attempts = 1
        try:
            response = await self.client.post(url, headers=headers, json=body, timeout=timeout)
            if (mode == 'auto' and response_format['type'] == 'json_schema'
                    and schema_format_unavailable(response)):
                self._schema_unavailable = True
                body['response_format'] = {'type': 'json_object'}
                attempts += 1
                response = await self.client.post(url, headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            usage = data.get('usage') or {}
            logger.info('llm_complete seconds=%.3f attempts=%d prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s',
                        time.perf_counter() - started, attempts, usage.get('prompt_tokens'),
                        usage.get('completion_tokens'),
                        (usage.get('completion_tokens_details') or {}).get('reasoning_tokens'))
            choice = data['choices'][0]
            if choice.get('finish_reason') == 'length':
                raise ProviderError('模型输出达到长度预算，分析未保存。请减少候选论文、降低思考强度或提高 LLM_MAX_TOKENS。')
            if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
                raise ProviderError('模型未完成结构化分析或拒绝了请求。请重试或更换模型。')
            result = json.loads(choice['message']['content'])
            if not isinstance(result, dict):
                raise ValueError('Expected an object')
            return result
        except httpx.TimeoutException as exc:
            raise ProviderError('LLM 分析超时，请重试。', 504) from exc
        except httpx.HTTPStatusError as exc:
            if schema_format_unavailable(exc.response):
                raise ProviderError('LLM 服务不支持当前结构化输出格式。请将 .env 中的 '
                                    'LLM_RESPONSE_FORMAT 设为 auto 或 json_object，并重启后端。') from exc
            raise ProviderError(f'LLM 服务返回 HTTP {exc.response.status_code}。请检查 key、模型和结构化输出支持。') from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise ProviderError('LLM 响应无效或网络异常；结果未写入缓存。') from exc
