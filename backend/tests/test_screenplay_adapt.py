"""screenplay_adapt 服务层测试：小说章节 → 漫剧剧本改写。

仅用 pytest + monkeypatch 模拟 http 调用，不依赖真实网络与密钥。
"""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import services.deepseek as ds
import services.screenplay_adapt as sa
from services.errors import UpstreamServiceError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, factory_state):
        self._state = factory_state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        state = self._state
        state["calls"].append(kwargs.get("json") or {})
        index = min(len(state["calls"]) - 1, len(state["responses"]) - 1)
        response = state["responses"][index]
        if isinstance(response, Exception):
            raise response
        return _FakeResponse(response)


def _ok_payload(text: str) -> dict:
    return {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}


def _patch_deepseek(monkeypatch):
    monkeypatch.setattr(ds, "runtime_model", lambda: "deepseek-v4-flash")
    monkeypatch.setattr(ds, "runtime_base_url", lambda: "https://example.test/v1")
    monkeypatch.setattr(ds, "_deepseek_auth_headers", lambda api_key=None: {"Authorization": "Bearer sk-test"})


def _chapters(*contents: str) -> list[dict]:
    return [
        {"story_id": 1, "chapter_id": index + 1, "title": f"第{index + 1}章", "content": content}
        for index, content in enumerate(contents)
    ]


def test_single_short_chapter_success(monkeypatch):
    _patch_deepseek(monkeypatch)
    state = {"calls": [], "responses": [_ok_payload("场景1：废墟 / 清晨 / 外景\n陈玄：这是哪里？")]}
    monkeypatch.setattr(sa.httpx, "AsyncClient", lambda *a, **kw: _FakeAsyncClient(state))

    result = asyncio.run(sa.adapt_novel_to_screenplay(chapters=_chapters("少年睁开眼，头顶是破裂的天花板。")))

    assert result["batch_count"] == 1
    assert len(result["source_refs"]) == 1
    ref = result["source_refs"][0]
    assert ref["chapter_id"] == 1
    assert ref["content_hash"] == sa.chapter_content_hash("少年睁开眼，头顶是破裂的天花板。")
    assert "场景1" in result["screenplay_text"]
    # payload 结构校验：system/user 消息 + thinking disabled
    payload = state["calls"][0]
    assert payload["thinking"] == {"type": "disabled"}
    assert "第1章" in payload["messages"][1]["content"]


def test_long_content_split_into_batches(monkeypatch):
    _patch_deepseek(monkeypatch)
    long_content = "段落内容。\n\n" * 2000  # 远超 8000 字
    state = {"calls": [], "responses": [_ok_payload(f"场景{i}：连续动作。") for i in range(1, 12)]}
    monkeypatch.setattr(sa.httpx, "AsyncClient", lambda *a, **kw: _FakeAsyncClient(state))

    result = asyncio.run(
        sa.adapt_novel_to_screenplay(chapters=_chapters(long_content), max_chars_per_call=8000)
    )

    assert result["batch_count"] > 1
    assert len(state["calls"]) == result["batch_count"]
    # 第二批的 user prompt 应带前文衔接摘要
    second_user = state["calls"][1]["messages"][1]["content"]
    assert "前文剧本摘要" in second_user
    assert "（无，本批为剧本开头）" not in second_user
    assert result["source_refs"][0]["content_hash"] == sa.chapter_content_hash(long_content.strip())


def test_upstream_500_raises_retryable(monkeypatch):
    _patch_deepseek(monkeypatch)
    response = httpx.Response(500, request=httpx.Request("POST", "https://example.test/v1/chat/completions"))
    state = {"calls": [], "responses": [httpx.HTTPStatusError("boom", request=response.request, response=response)]}
    monkeypatch.setattr(sa.httpx, "AsyncClient", lambda *a, **kw: _FakeAsyncClient(state))

    with pytest.raises(UpstreamServiceError) as excinfo:
        asyncio.run(sa.adapt_novel_to_screenplay(chapters=_chapters("正文内容。")))
    assert excinfo.value.code == "screenplay_adapt_failed"
    assert excinfo.value.retryable is True


def test_empty_chapters_raises(monkeypatch):
    with pytest.raises(ValueError):
        asyncio.run(sa.adapt_novel_to_screenplay(chapters=[]))


def test_all_empty_content_raises(monkeypatch):
    with pytest.raises(ValueError):
        asyncio.run(sa.adapt_novel_to_screenplay(chapters=_chapters("", "  ")))


def test_content_hash_stable_and_distinct():
    a = sa.chapter_content_hash("相同内容")
    b = sa.chapter_content_hash("相同内容")
    c = sa.chapter_content_hash("不同内容")
    assert a == b
    assert a != c
    assert len(a) == 32


def test_multi_chapter_merge_keeps_order(monkeypatch):
    _patch_deepseek(monkeypatch)
    state = {
        "calls": [],
        "responses": [_ok_payload("场景1：甲章。"), _ok_payload("场景2：乙章。")],
    }
    monkeypatch.setattr(sa.httpx, "AsyncClient", lambda *a, **kw: _FakeAsyncClient(state))

    result = asyncio.run(sa.adapt_novel_to_screenplay(chapters=_chapters("甲章正文。", "乙章正文。")))

    assert result["batch_count"] == 2
    assert result["screenplay_text"].index("场景1") < result["screenplay_text"].index("场景2")
    assert [ref["chapter_id"] for ref in result["source_refs"]] == [1, 2]
