"""作品删除（delete_story）回归测试：验证新增的非 CASCADE 子表均被显式清理且顺序正确。"""

import asyncio
from types import SimpleNamespace

from sqlalchemy.sql.expression import literal

import main


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _model_name(model):
    """从模型类或 InstrumentedAttribute 提取模型类名。"""
    cls = getattr(model, "class_", None)
    if cls is not None:
        return cls.__name__
    return getattr(model, "__name__", repr(model))


class _SqlLike:
    """可被真实 SQLAlchemy 表达式（in_/or_）接受的假对象。"""

    def __clause_element__(self):
        return literal(1)


class _Q(_SqlLike):
    """记录 query 调用链的假 Query。"""

    def __init__(self, recorder, model):
        self._recorder = recorder
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def subquery(self):
        return _SqlLike()

    def delete(self, synchronize_session=False):
        self._recorder.calls.append(("delete", _model_name(self._model)))

    def all(self):
        return []

    def first(self):
        return None


class _Db:
    """记录删除调用顺序的假 Session。"""

    def __init__(self):
        self.calls = []  # [("delete", model_name) | ("db_delete", model_name)]

    def query(self, model):
        return _Q(self, model)

    def delete(self, obj):
        self.calls.append(("db_delete", _model_name(obj)))

    def commit(self):
        pass


def _deleted_names(calls):
    return [name for kind, name in calls if kind == "delete"]


def _call_indexes(calls, name):
    return [i for i, (kind, n) in enumerate(calls) if n == name]


def _run_delete(monkeypatch, chapters):
    """以给定章节列表执行 delete_story，返回调用记录。"""
    story = SimpleNamespace(chapters=chapters, cover_image=None)
    recorder = _Db()
    monkeypatch.setattr(main, "_require_user", lambda request, db: SimpleNamespace())
    monkeypatch.setattr(main, "_require_story_for_user", lambda sid, user, db: story)
    monkeypatch.setattr(main, "_rmtree_best_effort", lambda *a, **k: None)
    monkeypatch.setattr(main, "_unlink_file", lambda *a, **k: None)
    result = main.delete_story(255, SimpleNamespace(), recorder)
    assert result == {"ok": True}
    return recorder.calls


def test_delete_story_cleans_all_new_non_cascade_tables(monkeypatch):
    """新增的 AiUsageEvent / AgentAttachment / StoryboardPromptPreset 都必须被显式删除。"""
    calls = _run_delete(monkeypatch, [SimpleNamespace(id=7)])
    names = set(_deleted_names(calls))
    assert "AiUsageEvent" in names
    assert "AgentAttachment" in names
    assert "StoryboardPromptPreset" in names


def test_delete_story_agent_attachment_before_conversation(monkeypatch):
    """AgentAttachment 引用 agent_conversations.id（RESTRICT），必须先于 AgentConversation 删除。"""
    calls = _run_delete(monkeypatch, [SimpleNamespace(id=7)])
    attachment_idx = _call_indexes(calls, "AgentAttachment")
    conversation_idx = _call_indexes(calls, "AgentConversation")
    assert attachment_idx and conversation_idx
    assert attachment_idx[0] < conversation_idx[0]


def test_delete_story_ai_usage_chapter_before_chapter_delete(monkeypatch):
    """AiUsageEvent.chapter_id 引用 chapters.id（RESTRICT），chapter 级清理必须先于 Chapter 删除。"""
    calls = _run_delete(monkeypatch, [SimpleNamespace(id=7)])
    ai_usage_idx = _call_indexes(calls, "AiUsageEvent")
    chapter_idx = _call_indexes(calls, "Chapter")
    assert ai_usage_idx and chapter_idx
    # AiUsageEvent 有两个清理点：chapter 级（先）与 story 级（后）
    assert ai_usage_idx[0] < chapter_idx[0]
    assert chapter_idx[0] < ai_usage_idx[-1]


def test_delete_story_story_level_cleanup_before_story_delete(monkeypatch):
    """AiUsageEvent story 级清理与 StoryboardPromptPreset 必须在 db.delete(story) 之前执行。"""
    calls = _run_delete(monkeypatch, [SimpleNamespace(id=7)])
    db_delete_idx = next(i for i, (kind, n) in enumerate(calls) if kind == "db_delete")
    assert db_delete_idx > _call_indexes(calls, "AiUsageEvent")[-1]
    assert db_delete_idx > _call_indexes(calls, "StoryboardPromptPreset")[0]


def test_delete_story_without_chapters_still_cleans_story_tables(monkeypatch):
    """无章节的作品删除时，story 级清理（AiUsageEvent / StoryboardPromptPreset）仍然执行。"""
    calls = _run_delete(monkeypatch, [])
    names = set(_deleted_names(calls))
    assert "AiUsageEvent" in names
    assert "StoryboardPromptPreset" in names
    assert "Chapter" not in names
