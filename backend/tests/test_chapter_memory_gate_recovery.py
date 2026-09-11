"""上一章连续性记忆门禁必须可自愈。

回归背景：长篇作品（如第 285 章）中，上一章的记忆提取任务一旦失败就会被
``_ensure_previous_chapter_memory_ready`` 永久视为终止态，之后每次生成都在 2 秒内
返回 503，不再调用模型，整本书被钉死。这里锁定修复后的行为：
1. 历史失败任务会在预算内重新提交，而不是立即报错；
2. 只有连续失败耗尽预算才向用户报错；
3. Agent 写入的记忆必须带 content_fingerprint，否则门禁永远判定“记忆未就绪”；
4. story_memory 的列表字段进入 prompt 时有保留上限，避免长篇上下文无界增长。
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _run(coro):
    return asyncio.run(coro)


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class _FakeQuery:
    """极简可链式查询桩：无论过滤条件如何都返回预置结果。"""

    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._result

    def all(self):
        return self._result if isinstance(self._result, list) else [self._result]


class _FakeSession:
    def __init__(self, *, chapter, task):
        self._chapter = chapter
        self._task = task

    def query(self, model):
        from models import BackgroundTask, Chapter

        if model is Chapter:
            return _FakeQuery(self._chapter)
        if model is BackgroundTask:
            return _FakeQuery(self._task)
        return _FakeQuery(None)

    def close(self):
        return None


def _make_failed_task(chapter_id: int, fingerprint: str):
    return SimpleNamespace(
        task_id="chapter_memory_7_deadbeef",
        task_type="chapter_memory_refresh",
        chapter_id=chapter_id,
        status="failed",
        error_message="第7章连续性记忆提取失败，请稍后重试",
        metadata_json={"content_fingerprint": fingerprint},
    )


def _make_chapter(chapter_id: int, content: str):
    return SimpleNamespace(
        id=chapter_id,
        chapter_number=7,
        novel_content=content,
        status="completed",
        memory_summary=None,
    )


def test_failed_previous_chapter_memory_task_is_resubmitted_and_recovers(monkeypatch):
    """失败任务不应立即 503：重新提交并等它成功后，门禁应放行。"""
    import main

    stale_content = "陈玄推开矿道的木门，风沙灌了进来。"
    chapter = _make_chapter(7, stale_content)
    failed_task = _make_failed_task(7, _fingerprint(stale_content))

    monkeypatch.setattr(main, "SessionLocal", lambda: _FakeSession(chapter=chapter, task=failed_task))
    monkeypatch.setattr(main, "_CHAPTER_MEMORY_WAIT_POLL_SECONDS", 0.0)

    submitted: list[str] = []

    async def fake_submit(prev_chapter, api_key):
        submitted.append(str(prev_chapter.id))
        # 模拟后台记忆任务成功：下一次轮询时门禁即视为“记忆就绪”。
        chapter.memory_summary = {
            "content_fingerprint": _fingerprint(stale_content),
            "chapter_summary": {"summary": "陈玄离开矿道"},
            "chapter_handoff": {"opening_must_continue": "承接矿道出口"},
        }
        return "chapter_memory_7_newtask"

    monkeypatch.setattr(main, "_submit_chapter_memory_refresh", fake_submit)

    _run(main._ensure_previous_chapter_memory_ready(11, 8, "sk-test"))

    assert submitted == ["7"], "失败任务应被重新提交一次"


def test_previous_chapter_memory_gate_raises_only_after_resubmit_budget_exhausted(monkeypatch):
    """只有连续失败耗尽预算，才向用户报 previous_chapter_memory_failed。"""
    import main
    from fastapi import HTTPException

    stale_content = "陈玄推开矿道的木门，风沙灌了进来。"
    chapter = _make_chapter(7, stale_content)
    failed_task = _make_failed_task(7, _fingerprint(stale_content))

    monkeypatch.setattr(main, "SessionLocal", lambda: _FakeSession(chapter=chapter, task=failed_task))
    monkeypatch.setattr(main, "_CHAPTER_MEMORY_WAIT_POLL_SECONDS", 0.0)
    monkeypatch.setattr(main, "_CHAPTER_MEMORY_MAX_RESUBMITS", 2, raising=False)

    submit_count = 0

    async def always_fail_submit(prev_chapter, api_key):
        nonlocal submit_count
        submit_count += 1
        # 每次重新提交都再次失败，模拟持续的上游故障。
        failed_task.status = "failed"
        return f"chapter_memory_7_retry{submit_count}"

    monkeypatch.setattr(main, "_submit_chapter_memory_refresh", always_fail_submit)

    with pytest.raises(HTTPException) as excinfo:
        _run(main._ensure_previous_chapter_memory_ready(11, 8, "sk-test"))

    detail = excinfo.value.detail
    assert excinfo.value.status_code == 503
    assert detail["code"] == "previous_chapter_memory_failed"
    assert detail["retryable"] is True
    # 预算内应尝试重新提交，而不是一次都不试就放弃。
    assert submit_count == main._CHAPTER_MEMORY_MAX_RESUBMITS


def test_memory_task_timeout_is_longer_than_inner_httpx_timeout(monkeypatch):
    """外层任务预算必须大于内层 300s，否则外层 TimeoutError 不可重试会钉死任务。"""
    import main

    assert main._CHAPTER_MEMORY_TASK_TIMEOUT_SECONDS > 300

    submitted: dict = {}

    async def fake_submit_task(*args, **kwargs):
        submitted["kwargs"] = kwargs
        return args[0]

    monkeypatch.setattr(main.task_manager, "submit_task", fake_submit_task)
    chapter = SimpleNamespace(id=23, story_id=12, chapter_number=9, novel_content="陈玄推门。")

    _run(main._submit_chapter_memory_refresh(chapter, "sk-test"))

    assert submitted["kwargs"]["timeout"] == main._CHAPTER_MEMORY_TASK_TIMEOUT_SECONDS


def test_agent_memory_write_records_content_fingerprint(monkeypatch):
    """Agent 写章节后的记忆必须带 content_fingerprint，否则门禁永远不放行。"""
    from services import story_state

    content = "陈玄离开灰市，回头看了一眼巷口。"
    chapter = SimpleNamespace(
        chapter_number=12,
        title="灰市",
        act=None,
        key_events=[],
        novel_content=content,
        memory_summary=None,
        story=SimpleNamespace(story_memory={}),
    )

    async def fake_summarize(story_context, chapter_info, novel_content, api_key=None):
        return {
            "chapter_summary": {"summary": "陈玄离开灰市"},
            "chapter_handoff": {"opening_must_continue": "承接巷口"},
            "story_memory_update": {"story_state": "离开灰市"},
        }

    refreshed = _run(story_state.refresh_chapter_memory_for_content(
        chapter=chapter,
        api_key="sk-test",
        story_context_func=lambda story: {},
        summarize_chapter_memory_func=fake_summarize,
        merge_story_memory_func=lambda existing, update, ch, summary: {"story_state": "离开灰市"},
    ))

    assert refreshed is True
    assert chapter.memory_summary["content_fingerprint"] == _fingerprint(content)


def test_story_memory_compact_bounds_unbounded_growth_fields():
    """长篇累积字段进入 prompt 前必须截断到保留上限。"""
    from services.story_state import build_story_memory_compact

    story_memory = {
        "story_state": "推进到第 285 章",
        "continuity_facts": [f"事实{i}" for i in range(200)],
        "open_loops": [f"悬念{i}" for i in range(200)],
        "resolved_loops": [f"已回收{i}" for i in range(200)],
        "long_term_foreshadowing": [f"伏笔{i}" for i in range(200)],
        "volume_summaries": [f"卷摘要{i}" for i in range(200)],
        "character_state_snapshots": [{"chapter": i} for i in range(200)],
        "recent_chapter_summaries": [{"chapter_number": i} for i in range(200)],
    }

    compact = build_story_memory_compact(story_memory)

    assert len(compact["continuity_facts"]) == 24
    assert len(compact["open_loops"]) == 24
    assert len(compact["resolved_loops"]) == 24
    assert len(compact["long_term_foreshadowing"]) == 30
    assert len(compact["volume_summaries"]) == 12
    assert len(compact["character_state_snapshots"]) == 5
    # recent_chapter_summaries 只保留上一章
    assert len(compact["recent_chapter_summaries"]) == 1
    assert compact["recent_chapter_summaries"][0]["chapter_number"] == 199
    # 保留的应是最近的条目
    assert compact["continuity_facts"][-1] == "事实199"
    assert compact["long_term_foreshadowing"][0] == "伏笔170"
