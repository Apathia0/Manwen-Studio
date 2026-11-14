"""测试 chapter_agents._chat_completion 的空 content guard。

覆盖路径：
1. content 为空 + reasoning_content 非空 → 抛结构化错误（不回退思考链，避免思路注入正文）。
2. content 为空 + reasoning_content 也为空 → 抛结构化错误，绝不静默返回空串。
3. content 非空 → 正常返回。

仅用 pytest + monkeypatch 模拟 http 调用，不依赖真实网络与密钥。
"""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import services.chapter_agents as ca
import services.deepseek as ds
from services.errors import WriterEmptyContentError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        return self._response


def _make_client_factory(payload: dict):
    def factory(*args, **kwargs):
        return _FakeAsyncClient(_FakeResponse(payload))

    return factory


def _patch_deepseek(monkeypatch):
    """让 _chat_completion 内部依赖的 deepseek 辅助函数不依赖真实环境配置。"""
    monkeypatch.setattr(ds, "runtime_model", lambda: "deepseek-v4-flash")
    monkeypatch.setattr(ds, "runtime_base_url", lambda: "https://example.test/v1")
    monkeypatch.setattr(ds, "_deepseek_auth_headers", lambda api_key=None: {"Authorization": "Bearer sk-test"})
    monkeypatch.setattr(ds, "_apply_runtime_params", lambda payload: payload)
    # 能力学习默认为 no-op，按需在具体用例中覆盖。
    monkeypatch.setattr(
        ca,
        "persist_model_capability_observation",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        ca,
        "load_model_capability",
        lambda base_url, model, db=None: {},
    )


def _call_chat_completion(monkeypatch, payload: dict):
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca.httpx, "AsyncClient", _make_client_factory(payload))
    return asyncio.run(
        ca._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            max_tokens=8192,
        )
    )


def _payload(content, finish_reason="stop", reasoning=None, reasoning_tokens=None):
    message = {"content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    payload = {"choices": [{"finish_reason": finish_reason, "message": message}]}
    if reasoning_tokens is not None:
        payload["usage"] = {
            "completion_tokens": 100,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        }
    return payload


def test_empty_content_with_reasoning_raises(monkeypatch):
    # 方案 B：即便有 reasoning_content，正文 content 为空也应抛异常，不回退思考链
    reasoning = "这是模型思考过程，正文 content 因 max_tokens 耗尽而缺失。"
    with pytest.raises(WriterEmptyContentError) as excinfo:
        _call_chat_completion(
            monkeypatch,
            _payload("", finish_reason="length", reasoning=reasoning, reasoning_tokens=3000),
        )
    assert excinfo.value.code == "writer_empty_content"
    assert excinfo.value.retryable is True
    assert excinfo.value.diagnostics["finish_reason"] == "length"
    assert excinfo.value.diagnostics["reasoning_content_len"] == len(reasoning)


def test_empty_content_with_empty_reasoning_raises(monkeypatch):
    with pytest.raises(WriterEmptyContentError) as excinfo:
        _call_chat_completion(
            monkeypatch,
            _payload("", finish_reason="length", reasoning=None, reasoning_tokens=3000),
        )
    assert excinfo.value.code == "writer_empty_content"
    assert excinfo.value.diagnostics["finish_reason"] == "length"
    assert excinfo.value.diagnostics["reasoning_content_len"] == 0


def test_non_empty_content_returns_normally(monkeypatch):
    content, finish_reason = _call_chat_completion(
        monkeypatch,
        _payload("这是正常正文内容。", finish_reason="stop", reasoning="思考", reasoning_tokens=100),
    )
    assert content == "这是正常正文内容。"
    assert finish_reason == "stop"


def test_reasoning_tokens_absent_does_not_crash(monkeypatch):
    # usage 中无 completion_tokens_details.reasoning_tokens 时不应报错
    content, finish_reason = _call_chat_completion(
        monkeypatch,
        _payload("正常正文。", finish_reason="stop"),
    )
    assert content == "正常正文。"
    assert finish_reason == "stop"


def _sequence_client_factory(payloads: list[dict]):
    """按调用顺序返回预设响应，用于覆盖重试链路。"""
    calls: list[dict] = []

    class _SeqClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None, **kwargs):
            calls.append({"url": url, "json": json})
            response = payloads[min(len(calls) - 1, len(payloads) - 1)]
            if isinstance(response, Exception):
                raise response
            return _FakeResponse(response)

    return _SeqClient, calls


def test_thinking_ate_budget_escalates_max_tokens(monkeypatch):
    """思考吃掉输出预算（finish_reason=length + reasoning_tokens≈max_tokens）时应放大预算重试而非原样重发。"""
    # 第一次：8192 预算被 8161 reasoning token 吃光；第二次：预算放大后返回正常正文。
    factory, calls = _sequence_client_factory(
        [
            _payload("", finish_reason="length", reasoning="思考" * 1000, reasoning_tokens=8161),
            _payload("完整章节正文。", finish_reason="stop", reasoning="少量思考", reasoning_tokens=100),
        ]
    )
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    content, finish_reason = asyncio.run(
        ca._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            max_tokens=8192,
        )
    )
    assert content == "完整章节正文。"
    assert finish_reason == "stop"
    assert len(calls) == 2
    assert calls[0]["json"]["max_tokens"] == 8192
    assert calls[1]["json"]["max_tokens"] == 16384


def test_thinking_ate_budget_no_reasoning_tokens_falls_back_to_char_estimate(monkeypatch):
    """上游不报告 reasoning_tokens 时，用 reasoning_content 长度粗估判定思考吃预算。"""
    factory, calls = _sequence_client_factory(
        [
            _payload("", finish_reason="length", reasoning="思" * 30000),
            _payload("正文内容。", finish_reason="stop"),
        ]
    )
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    content, _ = asyncio.run(
        ca._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            max_tokens=8192,
        )
    )
    assert content == "正文内容。"
    assert calls[1]["json"]["max_tokens"] == 16384


def test_short_finish_reason_still_uses_plain_retry(monkeypatch):
    """非思考吃预算的空正文（finish_reason=stop）保持原有重试逻辑，预算不变。"""
    factory, calls = _sequence_client_factory(
        [
            _payload("", finish_reason="stop", reasoning_tokens=10),
            _payload("第二次返回正文。", finish_reason="stop"),
        ]
    )
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    content, _ = asyncio.run(
        ca._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            max_tokens=8192,
        )
    )
    assert content == "第二次返回正文。"
    assert len(calls) == 2
    assert calls[1]["json"]["max_tokens"] == 8192


def test_thinking_budget_escalation_respects_boost_limit(monkeypatch):
    """思考预算升级达到上限后抛 WriterEmptyContentError，并记录 thinking_budget_boost 能力。"""
    observations: list[dict] = []

    def _fake_persist(*args, **kwargs):
        observations.append(kwargs)
        return {}

    empty = _payload("", finish_reason="length", reasoning="思考" * 1000, reasoning_tokens=32000)
    factory, calls = _sequence_client_factory([empty, empty, empty])
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca, "persist_model_capability_observation", _fake_persist)
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    with pytest.raises(WriterEmptyContentError) as excinfo:
        asyncio.run(
            ca._chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                api_key="sk-test",
                max_tokens=8192,
            )
        )
    assert excinfo.value.code == "writer_empty_content"
    # 8192 → 16384 → 32768 两次升级后仍空正文，最终抛错。
    assert [c["json"]["max_tokens"] for c in calls] == [8192, 16384, 32768]
    assert any(obs.get("thinking_budget_boost") for obs in observations)


def test_capability_memory_boosts_budget_before_request(monkeypatch):
    """能力记忆中已有 thinking_budget_boost 时，后续请求直接放大初始预算。"""
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(
        ca,
        "load_model_capability",
        lambda base_url, model, db=None: {"thinking_budget_boost": 1},
    )
    factory, calls = _sequence_client_factory([_payload("一次成功。", finish_reason="stop")])
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    content, _ = asyncio.run(
        ca._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            max_tokens=8192,
        )
    )
    assert content == "一次成功。"
    assert calls[0]["json"]["max_tokens"] == 16384


def test_upstream_504_retries_once_then_succeeds(monkeypatch):
    """网关瞬态 504（NewAPI 常见）应在 writer 层自动重试一次，而不是整章任务失败。"""
    factory, calls = _sequence_client_factory(
        [
            httpx.HTTPStatusError(
                "Gateway Timeout",
                request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
                response=httpx.Response(504, request=httpx.Request("POST", "https://example.test/v1/chat/completions")),
            ),
            _payload("重试后成功正文。", finish_reason="stop"),
        ]
    )
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca, "WRITER_UPSTREAM_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    content, finish_reason = asyncio.run(
        ca._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            max_tokens=8192,
        )
    )
    assert content == "重试后成功正文。"
    assert finish_reason == "stop"
    assert len(calls) == 2
    assert calls[1]["json"]["max_tokens"] == 8192


def test_upstream_400_not_retried(monkeypatch):
    """非瞬态 4xx（400/422 等）不触发 writer 层上游重试。"""
    factory, calls = _sequence_client_factory(
        [
            httpx.HTTPStatusError(
                "Bad Request",
                request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
                response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/v1/chat/completions")),
            ),
        ]
    )
    _patch_deepseek(monkeypatch)
    monkeypatch.setattr(ca.httpx, "AsyncClient", factory)
    from services.errors import UpstreamServiceError

    with pytest.raises(UpstreamServiceError) as excinfo:
        asyncio.run(
            ca._chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                api_key="sk-test",
                max_tokens=8192,
            )
        )
    assert excinfo.value.code == "writer_upstream_http_error"
    assert len(calls) == 1
