import json
import logging
import re
import time
from copy import deepcopy
from typing import Any
import httpx
from app.config import Settings
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r'\A```json\r?\n(?P<body>.*)\r?\n```\Z', re.DOTALL)
_JSON_SIMPLE_ESCAPES = frozenset('"\\/bfnrt')
_JSON_HEX_DIGITS = frozenset('0123456789abcdefABCDEF')


def _unwrap_json_fence(content: str) -> str:
    """Remove one strict, whole-response ``json`` fence around an object."""
    candidate = content.strip()
    match = _JSON_FENCE_RE.fullmatch(candidate)
    if not match:
        return content
    body = match.group('body').strip()
    # The fence is a transport convenience only.  Do not turn fenced arrays,
    # prose, or several JSON values into an accepted response.
    if not (body.startswith('{') and body.endswith('}')):
        return content
    return body


def _recoverable_json_error(error: json.JSONDecodeError) -> bool:
    """Whether the decoder identified one of the narrowly repairable errors."""
    return error.msg in {
        r'Invalid \escape',
        r'Invalid \uXXXX escape',
        'Invalid control character at',
    }


def _escape_raw_control(character: str) -> str:
    """Encode one raw JSON string control character without changing its value."""
    named = {'\b': r'\b', '\t': r'\t', '\n': r'\n', '\f': r'\f', '\r': r'\r'}
    return named.get(character, f'\\u{ord(character):04x}')


def _repair_json_string_literals(content: str) -> str:
    """Repair only invalid escapes and raw controls while scanning JSON strings.

    This deliberately does not balance quotes/brackets, discard trailing text,
    or extract one value from a larger response.  Valid JSON escapes are copied
    byte-for-byte so valid Unicode and existing string semantics are untouched.
    """
    repaired: list[str] = []
    in_string = False
    index = 0
    while index < len(content):
        character = content[index]
        if not in_string:
            repaired.append(character)
            if character == '"':
                in_string = True
            index += 1
            continue

        if character == '"':
            repaired.append(character)
            in_string = False
            index += 1
            continue

        if character == '\\':
            next_index = index + 1
            if next_index >= len(content):
                # Keep the response invalid if the string has no terminating
                # quote; this branch only makes a possible escaped slash safe.
                repaired.append('\\\\')
                index = next_index
                continue
            escaped = content[next_index]
            if escaped in _JSON_SIMPLE_ESCAPES:
                repaired.extend((character, escaped))
                index += 2
                continue
            if escaped == 'u' and next_index + 4 < len(content):
                digits = content[next_index + 1:next_index + 5]
                if len(digits) == 4 and all(digit in _JSON_HEX_DIGITS for digit in digits):
                    repaired.extend((character, escaped, digits))
                    index += 6
                    continue
            # An invalid slash is represented as a literal slash in the JSON
            # string.  Re-process the following character so it keeps its
            # normal string meaning (including a future raw control character).
            repaired.append('\\\\')
            index += 1
            continue

        if ord(character) < 0x20:
            repaired.append(_escape_raw_control(character))
        else:
            repaired.append(character)
        index += 1
    return ''.join(repaired)


def _parse_response_json(content: Any) -> dict[str, Any]:
    """Parse one model response, with narrowly scoped compatibility repair."""
    if not isinstance(content, str):
        raise TypeError('Expected JSON text')
    candidate = _unwrap_json_fence(content)
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as original_error:
        if not _recoverable_json_error(original_error):
            raise
        repaired = _repair_json_string_literals(candidate)
        if repaired == candidate:
            raise
        result = json.loads(repaired)
    if not isinstance(result, dict):
        raise ValueError('Expected an object')
    return result


def strictify_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAI strict-compatible copy of a Pydantic JSON schema.

    Strict structured outputs require every object property to be listed in
    ``required`` and reject object fields that allow additional properties.
    Pydantic expresses fields with defaults as optional, so nullable fields
    must remain nullable while their defaults are removed.  Walk every nested
    schema location (including ``$defs``, ``anyOf`` and array items) without
    changing the caller's schema.
    """
    normalized = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return

        # Defaults make a property optional to strict structured-output
        # validators.  The field's default is still applied by Pydantic when
        # parsing the model response after generation.
        node.pop('default', None)
        for value in node.values():
            visit(value)

        properties = node.get('properties')
        is_object = node.get('type') == 'object' or isinstance(properties, dict)
        if not is_object:
            return
        if not isinstance(properties, dict):
            properties = {}
        node['required'] = list(properties)
        node['additionalProperties'] = False

    visit(normalized)
    return normalized


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
        code = str(error.get('code', '')).lower()
    except (ValueError, AttributeError):
        return False

    # Invalid schema contents must remain visible instead of weakening the
    # request.  Do not treat ``json_schema`` itself as a schema error: many
    # providers prefix a model-capability rejection with "Invalid parameter",
    # for example ``response_format json_schema is not supported with this
    # model``.  That message describes the requested format, not the schema
    # contents.
    invalid_schema = (
        code in {'invalid_schema', 'schema_error', 'schema_validation_error'}
        or param.startswith('response_format.json_schema.schema')
        or re.search(
            r'(?:\binvalid|\bmalformed|\bnot\s+valid)\s+'
            r'(?:json[ _]?schema|schema)\b'
            r'|\bschema\s+(?:is|was|has been)\s+'
            r'(?:invalid|malformed|not\s+valid)\b'
            r'|\bschema\s+for\s+response_format\b'
            r'|\b(?:unsupported|unknown|unexpected)\s+'
            r'(?:schema\s+)?(?:keyword|property|field|type)\b',
            message,
        ) is not None
    )
    if invalid_schema:
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
        strict_schema = strictify_json_schema(schema)
        response_format: dict[str, Any] = {'type': 'json_object'}
        if mode == 'json_schema' or (mode == 'auto' and not self._schema_unavailable):
            response_format = {'type': 'json_schema', 'json_schema': {
                'name': 'field_analysis', 'strict': True, 'schema': strict_schema}}
        body = {'model': self.settings.llm_model, 'response_format': response_format,
                'messages': [{'role': 'system', 'content': system + '\nJSON schema:\n' + json.dumps(strict_schema)},
                             {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        body.update(self.settings.thinking_options)
        if self.settings.structured_temperature is not None:
            body['temperature'] = self.settings.structured_temperature
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
            content = choice['message']['content']
            try:
                return _parse_response_json(content)
            except json.JSONDecodeError as exc:
                logger.error('llm_json_parse_error type=%s line=%s col=%s len=%s',
                             type(exc).__name__, exc.lineno, exc.colno,
                             len(content) if isinstance(content, str) else 0)
                raise
        except httpx.TimeoutException as exc:
            raise ProviderError('LLM 分析超时，请重试。', 504) from exc
        except httpx.HTTPStatusError as exc:
            if schema_format_unavailable(exc.response):
                raise ProviderError('LLM 服务不支持当前结构化输出格式。请将 .env 中的 '
                                    'LLM_RESPONSE_FORMAT 设为 auto 或 json_object，并重启后端。') from exc
            status = exc.response.status_code
            if 500 <= status <= 599:
                # An upstream outage is operationally different from a bad
                # credential. Keep the upstream status visible while avoiding
                # its body (which may contain provider internals or secrets),
                # and do not retry business requests here.
                raise ProviderError(
                    f'LLM 服务暂时不可用（上游 HTTP {status}），请稍后重试。', 503,
                ) from exc
            if status in (401, 403):
                raise ProviderError(
                    f'LLM 服务鉴权失败（上游 HTTP {status}），请检查 key 和账号权限配置。', 502,
                ) from exc
            if status == 429:
                raise ProviderError(
                    'LLM 请求受到限流（上游 HTTP 429），请稍后重试。', 429,
                ) from exc
            raise ProviderError(
                f'LLM 服务返回 HTTP {status}。请检查请求格式、模型配置和结构化输出支持。',
            ) from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise ProviderError('LLM 响应无效或网络异常；结果未写入缓存。') from exc
