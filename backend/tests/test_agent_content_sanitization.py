import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from models import Chapter
from services import agent_service


class _FakeSession:
    def __init__(self):
        self.committed = False
        self.closed = False

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _run_tool(monkeypatch, chapter: Chapter, coroutine):
    session = _FakeSession()
    tracker = agent_service.PendingChangesTracker()
    context = agent_service.AgentRunContext(
        story_id=chapter.story_id,
        api_key=None,
        mode="execute",
        pending_changes=tracker,
    )

    monkeypatch.setattr(agent_service, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda db, chapter_id, story_id: chapter
        if chapter.id == chapter_id and chapter.story_id == story_id
        else None,
    )

    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = asyncio.run(coroutine)
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    return result, session, tracker


def _make_chapter(content: str) -> Chapter:
    return Chapter(
        id=611,
        story_id=202,
        chapter_number=1,
        title="测试章节",
        novel_content=content,
    )


def test_update_chapter_content_sanitizes_agent_generated_content(monkeypatch):
    chapter = _make_chapter("旧正文")
    raw_content = "他忽然明白了——原主为什么这样做。"

    result, session, tracker = _run_tool(
        monkeypatch,
        chapter,
        agent_service.update_chapter_content(chapter.id, raw_content),
    )

    assert result == {"ok": True, "chapter_id": chapter.id}
    assert chapter.novel_content == "他忽然明白了，原主为什么这样做。"
    assert tracker.get_full_data()[0]["new_value"] == chapter.novel_content
    assert session.committed is True


def test_batch_update_chapters_sanitizes_each_saved_chapter(monkeypatch):
    chapter = _make_chapter("旧正文")
    raw_content = "不是情绪——是一种极其平静的归属感。"

    result, session, tracker = _run_tool(
        monkeypatch,
        chapter,
        agent_service.batch_update_chapters(
            [{"chapter_id": chapter.id, "content": raw_content}]
        ),
    )

    assert result == {
        "ok": True,
        "results": [{"chapter_id": chapter.id, "ok": True}],
    }
    assert chapter.novel_content == "不是情绪，是一种极其平静的归属感。"
    assert tracker.get_full_data()[0]["new_value"] == chapter.novel_content
    assert session.committed is True


def test_rewrite_text_segment_only_sanitizes_rewritten_segment(monkeypatch):
    original = "需要改写的这一句。"
    untouched_prefix = "旧段落——必须保持原样。\n"
    chapter = _make_chapter(untouched_prefix + original)
    raw_rewritten = "新句子——不能保留破折号。"

    result, session, tracker = _run_tool(
        monkeypatch,
        chapter,
        agent_service.rewrite_text_segment(chapter.id, original, raw_rewritten),
    )

    expected = untouched_prefix + "新句子，不能保留破折号。"
    assert chapter.novel_content == expected
    assert result["new_content_length"] == len(expected)
    assert tracker.get_full_data()[0]["new_value"] == expected
    assert session.committed is True
